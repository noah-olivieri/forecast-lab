# QB-001 report: Elo plus backup-QB flag (v1)

Run `qb001-backup-flag-v1`, 2026-10-09. Pre-registration: `research/QB001_PREREG.md`
(pushed in `75d1b8b` before any QB-001 code or results existed).

**Result: success under the pre-registered test.** On 2015-2023, Elo+flag has lower Brier
than frozen Elo. The paired 95% CI is [-0.00333, -0.00096], which excludes zero in
Elo+flag's favor. The gain is small. Elo+flag is still well behind the historical
moneyline. This is development evidence, not a final test.

## Run

- Code: commit `8f55d54` (`src/lab/backtest/qb_flag.py`). No uncommitted changes to the
  run's code files.
- Offline, dotenv disabled, `uv run --locked --offline`. Exit 0. 1,207 seconds.
- The 20,000-draw sensitivity and CRPS were skipped, as instructed.
- No 2024-2025 data was read. The loader drops those rows before use.
- Outputs: `data/research/runs/qb001-backup-flag-v1/` (local, gitignored).

| Input or output | SHA-256 |
| --- | --- |
| Execution manifest | beb96e1167f33dc409eb47e3c7d4005df563ede36127dc9aa4e68a04e7b24fd3 |
| Odds manifest | ce33cc1ddd12aa83847c7f7859a6b13ace2e59b09e13e1cca4ec25b7981a48f4 |
| games.csv (nfldata 93a5221) | fb2a5a96e2bd0ddc1b6ddbd487c89857b216114e5ce296214e5b54b6d75bbc43 |
| games.jsonl | f13a74a057e1f7f50aa2fb670f9ec34a289eef0fafcc3382be95fbbd8232be2a |
| metrics.json | 35c7689efdac89d8045dce98a2d06d03cc7b44f7299677061e3c3c3d00231573 |

Integrity checks:

- Frozen Elo is called unchanged. Its probability matches RF-001's saved Elo prediction
  on all 4,861 games, with exact float equality.
- Elo minus moneyline on the decisive subset is 0.010843, the same as RF-001.
- At penalty 0, every probability equals frozen Elo.

## Chosen penalty

The chosen penalty is **2 points (50 Elo)**. My guess was 5 points.

The penalty was chosen on 2006-2014 only (2,403 games, ties scored as y = 0.5).

| Penalty (points) | Elo points | 2006-2014 Brier |
| --- | --- | --- |
| 0 | 0 | 0.218242 |
| 1 | 25 | 0.217461 |
| **2** | **50** | **0.217208** |
| 3 | 75 | 0.217445 |
| 4 | 100 | 0.218123 |
| 5 | 125 | 0.219189 |
| 6 | 150 | 0.220583 |
| 7 | 175 | 0.222244 |
| 8 | 200 | 0.224113 |

Brier falls up to 2 points and rises after it. Penalties of 5 points and up are worse than
no penalty.

## Flag rate

The flag fired far more often than I guessed (20% of games).

| Period | Games | Games with a flag | Share of games | Share of team-games |
| --- | --- | --- | --- | --- |
| 2006-2014 | 2,403 | 805 | 33.5% | 18.6% |
| 2015-2023 | 2,458 | 882 | 35.9% | 20.4% |

In 2015-2023, 8 games have a missing starter ID (all in 2023). They get no adjustment.
Every team in a 2015-2023 game had a usual starter.

## Test: Elo+flag vs frozen Elo, 2015-2023

Differences are Elo+flag minus Elo. Negative favors Elo+flag. The registered CI is the
paired four-week block bootstrap (5,000 replicates, seed 20261008). The one-week and
whole-season CIs are shown for reference.

### All games (n = 2,458)

| Metric | Elo | Elo+flag | Difference | Four-week CI95 | One-week CI95 | Whole-season CI95 |
| --- | --- | --- | --- | --- | --- | --- |
| Brier (primary) | 0.223733 | 0.222079 | -0.001654 | [-0.003331, -0.000965] | [-0.003061, -0.000237] | [-0.002583, -0.000777] |
| Log loss | 0.640740 | 0.636760 | -0.003980 | [-0.007760, -0.002499] | [-0.007199, -0.000759] | [-0.006218, -0.001854] |

### Decisive games with a historical moneyline (n = 2,448)

The reference is a historical moneyline. Its timing and book are unknown. Elo and Elo+flag
are scored as scalars, the same approximation RF-001 used.

| Metric | Elo | Elo+flag | Moneyline |
| --- | --- | --- | --- |
| Brier | 0.224514 | 0.222845 | 0.213671 |
| Log loss | 0.640422 | 0.636415 | 0.615462 |

| Comparison | Metric | Difference | Four-week CI95 |
| --- | --- | --- | --- |
| Elo+flag minus Elo | Brier | -0.001669 | [-0.003336, -0.000971] |
| Elo+flag minus Elo | Log loss | -0.004008 | [-0.007760, -0.002489] |
| Elo+flag minus moneyline | Brier | +0.009174 | [+0.006677, +0.012277] |
| Elo+flag minus moneyline | Log loss | +0.020952 | [+0.015340, +0.027872] |
| Elo minus moneyline | Brier | +0.010843 | [+0.008669, +0.014778] |

Both test populations' CIs exclude zero in Elo+flag's favor. The flag closes about 15%
of Elo's Brier gap to the moneyline (0.00167 of 0.01084). The moneyline is still clearly
better.

## Per-season results

Brier, all games, ties as y = 0.5. Difference is Elo+flag minus Elo.

| Season | Role | Games | Games flagged | Elo | Elo+flag | Difference |
| --- | --- | --- | --- | --- | --- | --- |
| 2006 | tuning | 267 | 23.6% | 0.239719 | 0.237593 | -0.002126 |
| 2007 | tuning | 267 | 46.1% | 0.215193 | 0.213287 | -0.001906 |
| 2008 | tuning | 267 | 35.6% | 0.217710 | 0.216520 | -0.001190 |
| 2009 | tuning | 267 | 36.7% | 0.205553 | 0.208107 | +0.002554 |
| 2010 | tuning | 267 | 33.3% | 0.233276 | 0.233425 | +0.000149 |
| 2011 | tuning | 267 | 35.6% | 0.213108 | 0.211714 | -0.001395 |
| 2012 | tuning | 267 | 27.7% | 0.219236 | 0.217113 | -0.002123 |
| 2013 | tuning | 267 | 31.1% | 0.214492 | 0.213248 | -0.001244 |
| 2014 | tuning | 267 | 31.8% | 0.205888 | 0.203870 | -0.002018 |
| 2015 | test | 267 | 34.8% | 0.225446 | 0.225277 | -0.000169 |
| 2016 | test | 267 | 27.7% | 0.216829 | 0.216603 | -0.000225 |
| 2017 | test | 267 | 32.2% | 0.217305 | 0.215084 | -0.002221 |
| 2018 | test | 267 | 37.1% | 0.221537 | 0.220033 | -0.001504 |
| 2019 | test | 267 | 36.3% | 0.223962 | 0.221194 | -0.002768 |
| 2020 | test | 269 | 35.3% | 0.217526 | 0.216242 | -0.001284 |
| 2021 | test | 285 | 38.2% | 0.234569 | 0.230391 | -0.004178 |
| 2022 | test | 284 | 40.5% | 0.222040 | 0.219446 | -0.002594 |
| 2023 | test | 285 | 40.0% | 0.233174 | 0.233335 | +0.000160 |

Elo+flag is better in 8 of 9 test seasons. 2015 and 2016 are close to zero. 2023 is
slightly worse.

## Weeks 1-4 diagnostic

Regular-season weeks 1-4 in 2015-2023, compared with all other games. This does not
change the success test.

| Games | n | Games flagged | Elo Brier | Elo+flag Brier | Difference |
| --- | --- | --- | --- | --- | --- |
| Weeks 1-4 | 570 | 55.1% | 0.229344 | 0.229232 | -0.000113 |
| Later weeks and playoffs | 1,888 | 30.1% | 0.222039 | 0.219920 | -0.002120 |

The flag fires in over half of early-season games. There it gives almost no gain. Nearly
all of the improvement comes from later weeks. This fits the known weakness: in early
weeks, many flags mark a new starter after an offseason change, not a backup.

## Flagged games only (descriptive)

This summary was not pre-registered. It was written into the code before the run.

In 2015-2023, the 882 flagged games have Elo Brier 0.223571 and Elo+flag Brier 0.218962
(difference -0.004610).

## Limitations

From the pre-registration:

- The actual starter is known after the fact. This is mild lookahead at T-24h. A live
  version would need the expected starter as known 24 hours before kickoff.
- A new starter after an offseason change is flagged as a backup at first. Under the rule
  as written, that lasts 4 games, not the "usually 3" the pre-registration estimated. In
  his 5th game the window is tied 4-4, and the tie goes to him as the most recent starter.
  The rule was applied as written.
- The 2015-2023 seasons were already viewed in RF-001. This is development evidence, not a
  final test.

Also:

- CIs are conditional on the chosen penalty. They leave out selection uncertainty.
- The moneyline's timing and book are unknown, so the moneyline comparison is not a T-24h
  market test.
- Early-2006 games have a short history (clarification 3). This affects only the penalty
  choice.
- Frozen Elo, its golden tests and `RESEARCH_PROTOCOL.md` were not changed. This report
  makes no promotion decision.
