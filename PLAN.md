# Econ & Sports Forecast Lab — PLAN

_Last verified: 2026-10-06. No real money; paper trading only._

## 1. Goal and success criteria

Build probabilistic models for (a) US economic event contracts (CPI, payrolls/unemployment, Fed decisions, weekly jobless claims and other high-frequency releases) and (b) NFL game contracts. Compare each forecast against prediction-market prices captured **at the same timestamp**, then paper trade for at least 8 weeks.

The project counts as done when:
- At least 8 consecutive weeks of **frozen, timestamped** forecasts exist, logged before each event.
- A report covers Brier score, log loss, a calibration (reliability) chart, Brier skill score vs. the naive baseline **and** vs. the market, and simulated P&L after fees, with bootstrap confidence intervals.
- It gives an honest conclusion, including "the market beat me" if that's what happened.

Calendar note: today is 2026-10-06 (about NFL week 5). Eight weeks of paper trading that starts by week 7 ends around week 14, before the regular season ends. **NFL ingest and logging must be live within about 2 weeks.** Fancier modeling can come later. A forecast logged late can't be backfilled.

## 2. Verified data sources

### 2.1 Prediction markets available in California

| Platform | CA status | Econ markets | NFL markets | Public price data / API | Fees (as of 2026-10-06) | Use in project |
|---|---|---|---|---|---|---|
| **Kalshi** (CFTC DCM) | Available statewide. Sports contracts are legally contested: on 2026-09-16 the Ninth Circuit ruled sports contracts entered from tribal land are unauthorized class III gaming. This doesn't affect paper trading. | Yes: `KXCPI`, `KXCPIYOY`, `KXPAYROLLS`, `KXU3`, `KXFED`, `KXFEDDECISION`, `KXGDP`, `KXJOBLESSCLAIMS` (weekly), `KXAAAGASW` (weekly gas), `KXMORTGAGERATE` (all confirmed live via API) | Yes: `KXNFLGAME`, `KXNFLSPREAD`, `KXNFLTOTAL` | **Yes, keyless.** `https://external-api.kalshi.com/trade-api/v2`: `/series`, `/events`, `/markets`, `/markets/{t}/orderbook`, `/trades`, candlesticks (1 min, 60 min, 1440 min). Markets settled before the **historical cutoff** (currently 2026-08-07) move to `/historical/*` endpoints. Basic tier allows about 20 reads/s. | Taker `ceil(0.07 × C × P × (1−P))`, maximum 1.75¢/contract at 50¢. Maker fee `0.0175 × …`, charged only on series where `fee_type = quadratic_with_maker_fees` (CPI, payrolls, Fed, NFL). `quadratic` series (jobless claims, gas) have no maker fee. **Read `fee_type`/`fee_multiplier` from `/series/{ticker}` and `/series/fee_changes`; don't hard-code them.** No deposit fee. | **Primary venue** for prices, history, and P&L simulation |
| **Polymarket US** (CFTC-regulated US exchange, open to US users since May 2026) | Available | Some econ markets; check which ones in M1 | Yes (e.g. slugs `aec-nfl-…`) | **Yes, keyless.** `https://gateway.polymarket.us/v1/markets` is public. Price history, book, and BBO endpoints are listed at docs.polymarket.us. (`api.prod.polymarketexchange.com` needs a bearer token.) | Taker `0.0695 × C × p × (1−p)` (maximum $1.74 per 100 contracts at 50¢). Makers get a **rebate** of `0.0125 × C × p × (1−p)`. Rounded to $0.01 with banker's rounding. Effective 2026-10-01; the schedule changes often. | **Secondary venue** for cross-market price comparison on NFL |
| **FanDuel Predicts** (FanDuel × CME Group; contracts listed on CME) | Available; sports in CA since 2026-01-14 | Yes (CPI, GDP, indexes) | Yes | **No public API found.** CME event-contract data is sold through CME DataMine (paid). | **[unverified]** Secondary sources disagree: "2% of potential payout" vs. "≥$0.01/contract CME fee plus markup". The primary help page wasn't reachable. | Out of scope for automated data. Optional manual spot checks. |
| **DraftKings Predictions** (runs on DK's own Railbird exchange, a DCM) | Available, including sports | Yes | Yes | **No public API found** | Tiered per contract: $0.01 (1–19¢ and 97–99¢), $0.02 (20–96¢). Secondary sources only. | Out of scope for automated data |
| Robinhood Prediction Markets | Available | Yes (Fed is liquid) | Yes | No public API; routes largely to Kalshi | $0.01 Robinhood commission + $0.01 exchange fee per contract | Kalshi prices stand in for it; mention in report |
| Coinbase Predictions | Available | Kalshi-powered | Kalshi-powered | Same order book as Kalshi | Kalshi fees plus any Coinbase markup | Same as Kalshi |
| Crypto.com Predict (CDNA) | Available | Few | Sports-focused | Not evaluated | — | Skip |

**Decision:** Kalshi is the system of record. Its order book, history, and machine-readable fee metadata are all public. Polymarket US gets snapshots for NFL so the report can show cross-venue disagreement. FanDuel and DraftKings are listed for completeness only.

### 2.2 Economic data

| Source | What | Access (verified) | Leakage notes |
|---|---|---|---|
| **FRED** (`api.stlouisfed.org/fred`) | CPI (`CPIAUCSL`, `CPILFESL`), payrolls (`PAYEMS`), unemployment (`UNRATE`), claims (`ICSA`, `CCSA`), gas (`GASREGW`), fed funds (`DFF`, `DFEDTARU`) | Free API key required (confirmed: keyless request returns 400) | FRED returns **revised** values. Never train on these for "what was known then". |
| **ALFRED** (same API, `realtime_start`/`realtime_end`, `/series/vintagedates`) | Point-in-time vintages of the series above | Same key | **Use for all features.** Payrolls revise heavily, and CPI SA factors revise every February. |
| **BLS Public API** (`api.bls.gov/publicAPI/v2`) | CPI components (e.g. `CUUR0000SA0`), CES, release schedule | v1 works keyless (confirmed); v2 needs a free key and allows 500 queries/day | Release times are 08:30 ET. Use the official release calendar as the cutoff for when an event became known. |
| **Cleveland Fed Inflation Nowcasting** (clevelandfed.org/indicators-and-data/inflation-nowcasting) | Daily nowcasts of CPI, core CPI, and PCE (MoM and YoY) | Public web page (HTTP 200). **No documented API.** Download/scrape the page's data in M1, and confirm whether it publishes a history of past nowcasts. | The nowcast changes daily. Snapshot it every day ourselves so we have a true point-in-time archive. Use only the nowcast dated **before** the forecast timestamp. |
| Federal Reserve (federalreserve.gov FOMC calendar) and DOL weekly claims release | Event dates and times | Public pages | Event calendar drives scheduling and cutoffs |

### 2.3 NFL data

| Source | What | Access (verified) | Leakage notes |
|---|---|---|---|
| **nflverse** via `nflreadpy` (PyPI v0.1.5) | Schedules/results, play-by-play with EPA, rosters, injuries, depth charts | Python package; raw `games.csv` at `github.com/nflverse/nfldata/raw/master/data/games.csv` (confirmed 200) | `games.csv` includes `spread_line`, `total_line`, and moneylines, but these are **closing** lines, known only at kickoff. Use them only for forecasts at T−0 or as a benchmark, never as a T−24h feature. Injury reports arrive during the week, so stamp each with the time we fetched it. |

## 3. Tech choices

- **Python 3.12** with **uv** (lockfile, reproducible env).
- **DuckDB**, one file `data/lab.duckdb`, plus raw API responses in Parquet under `data/raw/{source}/dt=YYYY-MM-DD/`. Raw data is immutable and append-only; DuckDB tables are rebuilt from it. DuckDB's `ASOF JOIN` is the main tool for point-in-time feature joins.
- `httpx` + `tenacity` (retry/backoff), `polars` or `pandas`, `pydantic` (API schemas), `scikit-learn` / `statsmodels` (models), `matplotlib` (calibration plots), `pytest`, `ruff`.
- **Scheduled jobs: GitHub Actions cron (decided).** A laptop asleep at T−1h would silently lose data, and runners are ephemeral. So the hourly collector commits compact Parquet files to an orphan **`data` branch** of the public repo. `main` holds code and `forecasts/` only, so the forecast-proof history stays clean. Cloud storage was rejected (extra account and secrets, and no remote-timestamped history). Local `launchd` backup is deferred.
  - Layout on `data`: `snapshots/hourly/<YYYYMMDD>T<HHMM>Z_<venue>.parquet` (UTC capture time), compacted by `compact.yml` every Monday 06:30 UTC into `snapshots/weekly/<ISOYEAR>-W<WW>_<venue>.parquet`. Compaction verifies row counts before deleting hourly files and is a normal commit, so old blobs stay in git history. It never force-pushes.
  - Actions cron can run 5–30 min late, so the **gap-check** (`gapcheck.yml`, hourly at :20) only judges hours that ended 15+ minutes ago and only the last 3 hours. It fails the run, which emails the repo owner. Run it by hand with `lookback=all` for a full audit.
  - Workflows: `collect.yml` (cron stays off until the snapshotter ships in M1), `gapcheck.yml`, `compact.yml`. Collector and compaction share a concurrency group so they never push to `data` at once. Helpers: `.github/scripts/data_worktree.sh` and `push_data.sh` (stages `snapshots/` by explicit path only).
  - None of these jobs needs `FRED_API_KEY`. It becomes a repo secret only when the ALFRED ingest runs in Actions (M4), and the owner adds it in the GitHub UI.
- Config: `config/markets.yaml` (series tickers, snapshot offsets), `.env` for the FRED/BLS keys (gitignored).

## 4. Repo structure

```
forecast-lab/
  PLAN.md
  pyproject.toml / uv.lock
  config/markets.yaml           # series to track, snapshot schedule, thresholds
  src/lab/
    ingest/                     # one module per source, raw -> Parquet
      kalshi.py  polymarket_us.py  fred_alfred.py  bls.py  cleveland_nowcast.py  nflverse.py
    store/                      # DuckDB schema, views, point-in-time helpers
      schema.sql  db.py  asof.py
    features/                   # econ.py, nfl.py — every function takes `as_of` timestamp
    models/                     # baselines.py, econ_cpi.py, econ_claims.py, econ_payrolls.py, fed.py, nfl_elo.py, nfl_glm.py
    contracts/                  # map model distribution -> contract prob (brackets, thresholds, spreads)
    backtest/                   # walk_forward.py, splits.py
    paper/                      # decide.py (trade rules), fees.py (per-venue), ledger.py (append-only)
    eval/                       # scoring.py (Brier, log loss, ECE, BSS), calibration.py, bootstrap.py, report.py
  jobs/                         # thin CLIs called by cron: snapshot_markets, snapshot_nowcast, forecast, settle, gapcheck
  .github/workflows/            # cron schedules
  tests/                        # leakage tests, fee tests, scoring tests
  reports/                      # weekly generated markdown/HTML + plots
  forecasts/                    # committed + pushed forecast batches (the proof; see 7a)
  data/                         # gitignored on main
```

## 5. Core tables (DuckDB)

- `market_snapshot(venue, market_ticker, event_ticker, ts_utc, yes_bid, yes_ask, no_bid, no_ask, last, volume, open_interest)`: append-only.
- `contract(venue, market_ticker, event_ticker, series, kind[threshold|bracket|winner|spread], strike_low, strike_high, close_ts, settle_ts, result)`
- `fee_schedule(venue, series, fee_type, multiplier, valid_from)`: fees are versioned so backtests use the fee that applied at the time.
- `econ_vintage(series_id, ref_period, value, realtime_start, realtime_end)` (ALFRED)
- `nowcast_snapshot(index, ref_period, value, fetched_ts)`
- `nfl_game`, `nfl_pbp`, `nfl_injury(…, fetched_ts)`
- `forecast(forecast_id, model, model_version, git_sha, market_ticker, as_of_ts, p_yes, created_ts)`: **append-only. Never updated.** `created_ts` must be earlier than the contract's `close_ts`, and the database enforces this with a check constraint.
- `paper_trade(forecast_id, side, qty, price, fee, decision_ts)` and `settlement(market_ticker, result, settled_ts)`

## 6. Modeling approach

Every forecast is a **probability for a specific contract**. Distribution models map to contracts by integrating over each bracket or threshold.

| Target | Naive baseline (always reported) | Model v1 |
|---|---|---|
| CPI MoM / YoY (`KXCPI`, `KXCPIYOY`) | Last month's print ± historical std of MoM changes, mapped to brackets | Normal (later Student-t) centered on the **Cleveland Fed nowcast** as of T. Spread = empirical std of past nowcast errors at the same horizon. |
| Payrolls / U-3 (`KXPAYROLLS`, `KXU3`) | 3-month trailing average ± empirical std (first-print vintages only) | Regression on first-print history, claims trend, and prior revisions, all from ALFRED |
| Weekly jobless claims (`KXJOBLESSCLAIMS`), the main **sample-size engine** | Last week's print with empirical weekly-change distribution | Seasonal model on the ALFRED `ICSA` vintage, plus holiday adjustments |
| Fed decision (`KXFED`, `KXFEDDECISION`) | "No change" with probability from the historical base rate | Mostly a **benchmark exercise**. Markets are very efficient here, so expect no edge and report that. |
| NFL winner (`KXNFLGAME`) | Home team wins with the historical home-win rate (≈0.55); also 0.5 | Elo (538-style, with margin-of-victory multiplier and preseason regression to the mean). Then a logistic model on EPA/play ratings, rest, and QB status, computed from games **before** the forecast date. |
| NFL spread/total (stretch) | Market-implied line ± historical std | Normal margin model from ratings |

The market itself is always a third benchmark. Beating the naive baseline is the minimum bar. Beating the market is the real test.

## 7. Walk-forward validation and leakage prevention

**Walk-forward:** expanding window. For each event *e* in time order, fit only on events that resolved before `as_of(e)`, predict *e*, then step forward. NFL refits weekly and econ refits per release. Hyperparameters (Elo K, home advantage, error windows) are tuned only on seasons ≤2023 and frozen before the 2024–2025 backtest. Run that backtest once, then paper trade live in 2026.

**Leakage rules, enforced in code:**
1. Every feature function signature is `f(as_of: datetime) -> …`. Queries go through `store/asof.py`, which filters `realtime_start <= as_of` (ALFRED), `fetched_ts <= as_of` (our snapshots), and `game_ts < as_of` (NFL).
2. Never use FRED's latest values as features. Use ALFRED vintages only.
3. Never use closing lines or post-kickoff injury info at T−24h.
4. The market price compared against a forecast must come from the **same** `as_of` snapshot.
5. Forecasts are append-only, stamped with git SHA and `created_ts`. Any re-run produces a new `model_version`. Nothing is overwritten. The DuckDB `forecast` table is the working store; the committed CSV in `forecasts/` (7a) is the proof of record.
6. **Leakage unit tests:** (a) shift a target value into the future and assert features don't change; (b) for random events, assert no row used has a timestamp ≥ `as_of`; (c) a "future-peek" canary model that is allowed to cheat should score suspiciously well, which proves the test harness can detect leakage.

### 7a. Forecast proof: commit and push before the event

Git history is the evidence that a forecast was made before its event, so each forecast batch is committed and pushed to the remote **before** the event closes.

- Each batch is one CSV: `forecasts/YYYY-MM-DD/<job>_<as_of_utc>.csv` (for example `forecasts/2026-10-12/nfl_2026-10-11T16-00Z.csv`). It lives in `forecasts/`, not `data/`, because `data/` is gitignored.
- Columns: `forecast_id, model, model_version, git_sha, venue, market_ticker, as_of_ts, p_yes, created_ts, event_close_ts, market_yes_ask, market_yes_bid`. The market price used for comparison is stored in the row, so the later comparison can't be quietly redone with a different price.
- Files are append-only. A correction is a new file with a new `model_version`. A committed file is never edited or deleted.
- The `forecast` job commits the batch and pushes it. Only after the push succeeds does it insert the rows into DuckDB. If the push fails, no forecast counts as made.
- Only `forecasts/` is staged, and the job stages it by explicit path, never `git add -A`. `.env` and `data/` can't be picked up.
- **Evaluation gate:** the scorer drops any forecast whose commit time is not before `event_close_ts`. It reads the time with `git log --format=%cI -- <file>`, and for pushed commits it can be cross-checked against the remote host's push or commit timestamps.
- Honest limit: a committer date is set by the committer's own clock and can be forged. A forced push could also rewrite history. The remote's own record of when it received commits is the stronger evidence, so the repo must be pushed regularly, branch protection should block force-pushes on `main`, and a third party (a GitHub-hosted remote) is the timestamp authority. In the interview, say what this proves and what it doesn't.
- Prerequisite: a git remote. None is configured yet.

## 8. Paper trading rules (fixed before week 1)

- Snapshot schedule: econ at T−7d, T−1d, T−1h before release. NFL at T−24h and T−1h before kickoff, plus the weekly open.
- Trade if `p_model − ask_yes > fee_per_contract + edge_threshold` (or the symmetric condition on NO). The trade fills at the **ask** in the snapshot, never the mid. No fills larger than displayed size.
- Size: 1 contract flat (clean comparison), with ¼-Kelly capped at 2% of a $1,000 notional bankroll shown alongside.
- Fees come from `paper/fees.py`, which is driven by `fee_schedule`. Both Kalshi and Polymarket US are simulated.
- Report gross P&L, fees, net P&L, number of trades, hit rate, and max drawdown.

## 9. Evaluation

- Brier score, log loss, and **Brier skill score** vs. both the naive baseline and the market.
- Calibration: reliability diagram (10 bins, with counts) and ECE. Optionally a Murphy decomposition (reliability, resolution, uncertainty).
- **Bootstrap CIs**, block-bootstrapped by event, because brackets within one CPI release are correlated. Paired difference test (model vs. market Brier on the same contracts).
- Expected sample size over 8 weeks: about 110 NFL games, about 8 claims releases, about 2 CPI, about 2 jobs reports, and 1–2 FOMC meetings. **Econ conclusions will be underpowered.** The plan says so up front, so we don't over-claim.

## 10. Build order

| Milestone | Deliverable | Target |
|---|---|---|
| **M0** | Repo scaffold, uv, ruff/pytest, DuckDB schema, `.env` keys (FRED, BLS) | Day 1–2 |
| **M1** | Kalshi + Polymarket US ingest (markets, orderbook snapshots, history, fee metadata). **Cron snapshots live.** Cleveland nowcast daily snapshot live. | by ~Oct 12 |
| **M2** | nflverse ingest, Elo model, home-win baseline, forecast logger. **NFL paper trading starts** (week 6–7). | by ~Oct 16 |
| **M3** | `eval/` scoring + weekly auto-report. Leakage tests. | by ~Oct 20 |
| **M4** | ALFRED/BLS ingest. Claims and CPI models with baselines. Econ paper trading starts. | by ~Oct 27 |
| **M5** | Historical walk-forward backtests (NFL 2018–2025 using nflverse plus Kalshi history where available; econ using ALFRED plus Kalshi historical endpoints). | weeks 3–5 |
| **M6** | Payrolls model, NFL GLM v2, Polymarket cross-venue comparison | weeks 4–6 |
| **M7** | 8-week final report: calibration, BSS, P&L after fees, honest conclusions | ~mid-Dec |

Rule: only ingest and logging are on the critical path. Model improvements ship as new `model_version`s alongside the old ones and never replace them.

## 11. Risks and open items

- Fee schedules change often (Polymarket US changed on 2026-10-01). Version them and re-check monthly.
- FanDuel and DraftKings fees aren't confirmed from primary sources, and neither has a public API.
- Cleveland Fed has no API, so scraping may break. Keep our own daily archive.
- Kalshi's historical cutoff moves forward over time. Backfill from `/historical/*` early.
- GitHub Actions cron can run late or skip a run. The gap-check job alerts on it. A local launchd backup is deferred, so a missed hour stays missed, since market snapshots can't be backfilled.
- GitHub disables scheduled workflows on a repo with no activity for 60 days. Regular forecast pushes keep it active, but check the Actions tab if collection stops.
- The `data` branch grows with history. Weekly compaction keeps the tree small, not the git history. Re-evaluate if the repo nears a few hundred MB.
- A government shutdown or BLS delay would shift release dates. Drive scheduling from the calendar, not fixed dates.

## 12. Concepts you must be able to explain in an interview

**Forecast evaluation**
- Brier score and its decomposition (reliability, resolution, uncertainty). Why it's a *proper* scoring rule.
- Log loss vs. Brier: sensitivity to confident misses.
- Calibration vs. discrimination (sharpness). Reliability diagrams, ECE.
- Brier skill score and why the naive baseline matters.
- Statistical power and small samples. Why 2 CPI prints prove nothing. Block bootstrap for correlated contracts.

**Validation hygiene**
- Walk-forward / expanding-window validation vs. k-fold, and why shuffling time series leaks.
- Data leakage types: look-ahead, revised-data (vintage) leakage, target leakage, closing-line leakage, survivorship.
- Point-in-time data, ALFRED vintages, as-of joins.
- Overfitting via repeated backtests (the garden of forking paths). Why hyperparameters were frozen before the holdout.

**Markets**
- Event contracts: a binary pays $1, so price ≈ risk-neutral probability. Why price ≠ true probability (fees, favorite–longshot bias, risk premia, liquidity).
- Bid/ask spread, executing at the ask vs. the mid, order-book depth, slippage.
- Maker vs. taker. Why quadratic fees `θ·p(1−p)` peak at 50¢. Computing break-even edge after fees.
- Expected value, Kelly criterion, fractional Kelly, bankroll and drawdown.
- Market efficiency. Why "the market beat my model" is a valid, useful result.
- Regulatory context: CFTC DCMs vs. state sportsbooks. California's position, and the tribal gaming litigation.

**Models**
- Elo: K-factor, home advantage, margin-of-victory multiplier, regression to the mean.
- EPA (expected points added), and why it's more stable than win-loss record.
- Mapping a continuous forecast distribution to bracket and threshold contract probabilities.
- Nowcasting: mixed-frequency data, what the Cleveland Fed model uses (oil, gasoline, past inflation).
- Data revisions (payroll benchmark revisions, CPI seasonal-factor revisions).

**Engineering**
- Why DuckDB/Parquet and why raw data is immutable and append-only.
- Idempotent scheduled jobs, retries, gap detection.
- Reproducibility: lockfiles, git-SHA-stamped forecasts, pre-registration of trading rules.

## 13. Sources (checked 2026-10-06)

- Kalshi API docs: docs.kalshi.com (market data quick start, historical data, rate limits, fee rounding). Live: `external-api.kalshi.com/trade-api/v2/series/{KXCPI…}`, `/historical/cutoff`
- Kalshi fee formula: kalshi.com/docs/kalshi-fee-schedule.pdf (via secondary summaries; the PDF was rate-limited at check time). Series `fee_type` confirmed via API.
- Polymarket US: docs.polymarket.us (fees.md, environments, llms.txt). Live: `gateway.polymarket.us/v1/markets`
- Kalshi CA status / Ninth Circuit: covers.com, cbssports.com, si.com (Oct 2026 pages)
- FanDuel Predicts: gamblinginsider.com, defirate.com, marketmath.io. CME × FanDuel: investmentexecutive.com
- DraftKings Predictions / Railbird: bonus.com, casino.org, defirate.com, nasdaq.com
- Robinhood / Coinbase / Crypto.com: marketmath.io, help.coinbase.com, next.io
- FRED/ALFRED: fred.stlouisfed.org/docs/api. BLS: api.bls.gov. Cleveland Fed: clevelandfed.org/indicators-and-data/inflation-nowcasting
- nflverse: pypi.org/project/nflreadpy, github.com/nflverse/nfldata
