# Forecast Lab — Research Protocol (NFL, live test)

Author: Noah Olivieri. This file is fixed before results. Any change is a new dated section
under "Changes"; nothing above it is edited.

## 1. Question
Do model probabilities contain information beyond Kalshi / Polymarket US prices?

## 2. Forecasts
- Target: P(home team wins), one probability per game per model.
- Models: elo-538-default-v0, home-rate-v0, market-mid-v0 (Kalshi, Polymarket US). All frozen.
- Horizon: T-24h. Window [kickoff − 24h, kickoff − 21h). The first successful automated run in
  the window makes the forecast. No forecast by the close = MISSED, counted in the denominator.
- Eligible: every NFL game (regular season and postseason) whose kickoff is at least 24h after
  automation go-live. No game is selected or skipped by hand.
- Why: T-24h compares the model and the market before injury reports and pre-game
  news are out. Elo doesn't use that news, so a later forecast would only give the market extra
  information. The window closes at K−21h so every game is forecast at about the same horizon,
  while still allowing about 12 automated attempts.

## 3. Pilot
- 2026_05_TB_DAL is included in the live sample. Manual pilot made under the earlier
  "pushed by T-24h" rule; horizon 24h07m.
- Why: TB@DAL was the first game after launch, not chosen because it looked
  interesting, so including it adds no selection bias. Deciding before kickoff means the result
  can't influence whether it counts.

## 4. Scoring
- Primary: Brier score. Secondary: log loss. Also: calibration, paired model-vs-market
  differences with confidence intervals, sample size.
- Each model is scored once per game (rows repeated per venue are deduplicated).
- Ties: scored as y = 0.5 for both Brier and log loss; the tie count is reported.
- Why: Brier and log loss are proper scoring rules, so honest probabilities score
  best. Brier is primary because it is bounded and easy to explain; log loss is secondary
  because it punishes confident wrong forecasts. They are chosen before any results so I can't
  switch to whichever metric makes the model look better. Ties count as half a win (y = 0.5),
  consistent with how Elo already treats them.

## 5. What will NOT be claimed
- No claim of an edge from model-market disagreement alone.
- No conclusion before 1,000 settled games. Interim results may be shown with
  confidence intervals and labeled preliminary.
- Live results and historical backtests are always reported separately.
- Additional market benchmarks (e.g., devigged sportsbook lines) may be added later via a dated
  change; they apply only to games after that change is committed.

## Changes
(none yet)
