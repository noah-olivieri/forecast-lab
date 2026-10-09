# QB-002 report: separate new starters from backups (v2)

Run `qb002-new-starter-v1`, 2026-10-09. Pre-registration: `research/QB002_PREREG.md`
(pushed in `10832a4` before any QB-002 code or results existed).

**Result: null.** QB-002 did not beat QB-001 on the pre-registered test. On 2015-2023, the
Brier difference is -0.00049, but the 95% CI is [-0.00127, +0.00054]. It includes zero.

QB-002 still beats frozen Elo, as QB-001 did. It is still well behind the historical
moneyline. This is development evidence only.

## Run

- Code: commit `37c7ac3` (`src/lab/backtest/qb_flag.py`, `--new-starter-rule`). No
  uncommitted changes to the run's code files.
- Offline, dotenv disabled, `uv run --locked --offline`. Exit 0.
- Wall clock was 6,671 seconds, but CPU time was about the same as QB-001 (1,516 s user).
  The Mac probably slept or was throttled during the run. `caffeinate` was not used. This
  affects run time only.
- No 2024-2025 data was read.
- Outputs: `data/research/runs/qb002-new-starter-v1/` (local, gitignored).

| Input or output | SHA-256 |
| --- | --- |
| Execution manifest | beb96e1167f33dc409eb47e3c7d4005df563ede36127dc9aa4e68a04e7b24fd3 |
| Odds manifest | ce33cc1ddd12aa83847c7f7859a6b13ace2e59b09e13e1cca4ec25b7981a48f4 |
| games.csv (nfldata 93a5221) | fb2a5a96e2bd0ddc1b6ddbd487c89857b216114e5ce296214e5b54b6d75bbc43 |
| games.jsonl | 577533f9bc3fc2b9a7e8620c63d22192090f8e5a44235e42af86941dd42ff9df |
| metrics.json | 02955a1b2b910d9699bfa815880489245d213746f0103fcc98781828f5485526 |

Integrity checks:

- The QB-001 fields in this run are identical to the saved `qb001-backup-flag-v1` run on
  all 4,861 games.
- QB-001 again chose 2 points.
- Frozen Elo scores match QB-001 and RF-001.

## Primary test: QB-002 vs QB-001, 2015-2023, all games

Each model is scored at its own chosen penalty: QB-001 at 2 points, QB-002 at 3 points.
Differences are QB-002 minus QB-001. Negative favors QB-002. The registered CI is the
paired four-week block bootstrap (5,000 replicates, seed 20261008). The one-week and
whole-season CIs are shown for reference.

| Metric | QB-001 | QB-002 | Difference | Four-week CI95 | One-week CI95 | Whole-season CI95 |
| --- | --- | --- | --- | --- | --- | --- |
| Brier (primary) | 0.222079 | 0.221585 | -0.000494 | [-0.001269, +0.000536] | [-0.001523, +0.000544] | [-0.001575, +0.000609] |
| Log loss | 0.636760 | 0.635697 | -0.001062 | [-0.002884, +0.001444] | [-0.003468, +0.001348] | [-0.003346, +0.001232] |

The CI includes zero, so this is a null result. The point estimate leans toward QB-002,
but the data cannot tell the two apart.

## Chosen penalty

The chosen penalty is **3 points (75 Elo)**, picked on 2006-2014 only (2,403 games, ties
scored as y = 0.5). QB-001 chose 2 points on the same games.

| Penalty (points) | QB-001 Brier | QB-002 Brier |
| --- | --- | --- |
| 0 | 0.218242 | 0.218242 |
| 1 | 0.217461 | 0.217336 |
| 2 | **0.217208** | 0.216836 |
| 3 | 0.217445 | **0.216713** |
| 4 | 0.218123 | 0.216932 |
| 5 | 0.219189 | 0.217453 |
| 6 | 0.220583 | 0.218232 |
| 7 | 0.222244 | 0.219225 |
| 8 | 0.224113 | 0.220387 |

With new starters removed, the best penalty moved up by one point. Large penalties hurt
less than under QB-001.

## Flag rate

| Period | Games | QB-001 games flagged | QB-002 games flagged | QB-002 team-games flagged |
| --- | --- | --- | --- | --- |
| 2006-2014 | 2,403 | 33.5% | 25.8% | 13.9% |
| 2015-2023 | 2,458 | 35.9% | 26.4% | 14.2% |

Not pre-registered: in 2015-2023, 305 QB-001 team flags were exempted by the new rule.
300 of them were in weeks 1-4.

## QB-002 vs frozen Elo

Differences are QB-002 minus Elo. Negative favors QB-002.

| Population | n | Metric | Elo | QB-002 | Difference | Four-week CI95 |
| --- | --- | --- | --- | --- | --- | --- |
| All games | 2,458 | Brier | 0.223733 | 0.221585 | -0.002148 | [-0.004146, -0.000915] |
| All games | 2,458 | Log loss | 0.640740 | 0.635697 | -0.005043 | [-0.009685, -0.002170] |
| Decisive, moneyline | 2,448 | Brier | 0.224514 | 0.222374 | -0.002141 | [-0.004146, -0.000891] |
| Decisive, moneyline | 2,448 | Log loss | 0.640422 | 0.635418 | -0.005004 | [-0.009658, -0.002091] |

Both CIs exclude zero in QB-002's favor.

## QB-002 vs the moneyline reference

The reference is a historical moneyline. Its timing and book are unknown. Models are
scored as scalars on decisive games, the same approximation RF-001 used.

| Model | Brier | Log loss |
| --- | --- | --- |
| Frozen Elo | 0.224514 | 0.640422 |
| QB-001 (for reference) | 0.222845 | 0.636415 |
| QB-002 | 0.222374 | 0.635418 |
| Moneyline | 0.213671 | 0.615462 |

QB-002 minus moneyline: Brier +0.008702, CI [+0.006254, +0.011901]; log loss +0.019956,
CI [+0.014547, +0.027139]. The moneyline is still clearly better. QB-002 closes about 20%
of Elo's Brier gap to it (QB-001: about 15%).

## Per-season results

Brier, all games, ties as y = 0.5.

| Season | Role | QB-002 games flagged | Elo | QB-001 | QB-002 | QB-002 minus QB-001 | QB-002 minus Elo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2006 | tuning | 23.6% | 0.239719 | 0.237593 | 0.237170 | -0.000423 | -0.002549 |
| 2007 | tuning | 37.5% | 0.215193 | 0.213287 | 0.214950 | +0.001662 | -0.000244 |
| 2008 | tuning | 27.7% | 0.217710 | 0.216520 | 0.215600 | -0.000920 | -0.002110 |
| 2009 | tuning | 26.6% | 0.205553 | 0.208107 | 0.205336 | -0.002771 | -0.000217 |
| 2010 | tuning | 27.7% | 0.233276 | 0.233425 | 0.234013 | +0.000587 | +0.000737 |
| 2011 | tuning | 24.0% | 0.213108 | 0.211714 | 0.211412 | -0.000301 | -0.001696 |
| 2012 | tuning | 15.4% | 0.219236 | 0.217113 | 0.216363 | -0.000750 | -0.002873 |
| 2013 | tuning | 24.0% | 0.214492 | 0.213248 | 0.211350 | -0.001897 | -0.003142 |
| 2014 | tuning | 25.5% | 0.205888 | 0.203870 | 0.204222 | +0.000353 | -0.001665 |
| 2015 | test | 25.5% | 0.225446 | 0.225277 | 0.226158 | +0.000880 | +0.000712 |
| 2016 | test | 20.6% | 0.216829 | 0.216603 | 0.213913 | -0.002690 | -0.002915 |
| 2017 | test | 25.5% | 0.217305 | 0.215084 | 0.216689 | +0.001605 | -0.000616 |
| 2018 | test | 24.7% | 0.221537 | 0.220033 | 0.219744 | -0.000289 | -0.001793 |
| 2019 | test | 27.3% | 0.223962 | 0.221194 | 0.223042 | +0.001849 | -0.000919 |
| 2020 | test | 27.5% | 0.217526 | 0.216242 | 0.213388 | -0.002854 | -0.004138 |
| 2021 | test | 26.0% | 0.234569 | 0.230391 | 0.227927 | -0.002464 | -0.006642 |
| 2022 | test | 29.9% | 0.222040 | 0.219446 | 0.219611 | +0.000165 | -0.002429 |
| 2023 | test | 29.8% | 0.233174 | 0.233335 | 0.232799 | -0.000535 | -0.000375 |

QB-002 beats QB-001 in 5 of 9 test seasons and loses in 4. It beats Elo in 8 of 9 test
seasons (not 2015).

## Weeks 1-4 vs later weeks

Regular-season weeks 1-4 in 2015-2023, compared with all other games.

| Games | n | QB-001 flagged | QB-002 flagged | Elo | QB-001 | QB-002 | QB-002 minus QB-001 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Weeks 1-4 | 570 | 55.1% | 14.7% | 0.229344 | 0.229232 | 0.228428 | -0.000803 |
| Later weeks and playoffs | 1,888 | 30.1% | 29.9% | 0.222039 | 0.219920 | 0.219519 | -0.000400 |

The new rule did what it was built to do. It cut early-season flags from 55% to 15% of
games. Early-season Brier improved a little. Later games barely changed, since the rule
almost never applies there. Neither change is large enough to show up in the primary test.

## Not pre-registered

- The count of exempted flags (305, of which 300 were in weeks 1-4).
- QB-001's moneyline-subset scores, shown for reference.
- The share of the moneyline gap closed (about 20% vs 15%).

## Limitations

From the pre-registration:

- Same lookahead as QB-001. The actual starter is known after the fact.
- A backup who starts every game from week 1 (for example after a preseason injury) is
  never flagged during that stint.
- This is the third test on 2015-2023, so it is development evidence only.

Also:

- CIs are conditional on each model's chosen penalty. They leave out selection
  uncertainty.
- The moneyline's timing and book are unknown, so the moneyline comparison is not a T-24h
  market test.
- Frozen Elo, its golden tests and QB-001's default behavior were not changed. This report
  makes no promotion decision.
