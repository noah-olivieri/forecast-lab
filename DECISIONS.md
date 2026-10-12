# Decisions

## 2026-10-08: One game is not evidence (TB@DAL pilot)

Decision: No conclusion from single games, including the TB@DAL pilot. The 1,000 settled
game threshold stays.

What happened: TB won 24-16 at DAL, so y = 0 (unofficial until nflverse settles it).
Elo v0 had DAL at 67.8%, Kalshi 79.5%, Polymarket 79.6%. Elo scored better on Brier
(0.460 vs 0.632) and log loss (1.133 vs 1.585).

My reasoning (my words, typos fixed): "This result can't tell me Elo is better because it
was a severe upset, which meant that my model was just less confident. It doesn't
necessarily mean that it was more accurate because it's only scored on the log and Brier
scale. The less confident model would technically score higher, not necessarily making it
better."

Review note (from Claude): An 80% favorite loses about 1 game in 5, so this wasn't a
severe upset. Brier and log loss are the right metrics; the problem is one game. If the
market's 79.5% were the true probability, the market would beat Elo by about 0.014 Brier
per game on average. This one game swung 0.17 the other way.

Action: None. The game gets settled and scored through Phase B/C like any other.

## 2026-10-08: Keep frozen Elo; RF-001 does not replace it

Decision: Elo v0 stays the baseline. RF-001 is not promoted.

What happened: First reconstructed backtest (run rf001-reconstructed-2006-2023-first-v1),
2015-2023 outer seasons. All games (2,458): RF-001 Brier 0.2260, Elo 0.2237. Paired
difference RF-001 minus Elo is +0.0022, 95% CI [-0.0003, +0.0056], so no clear difference.
Decisive games with a historical moneyline (2,448): moneyline 0.2137, Elo 0.2245,
RF-001 0.2269. RF-001 minus moneyline is +0.0132, 95% CI [+0.0102, +0.0186].

My reasoning (my words): "Both models only use final scores of past games and the market
also knows starting players, starting quarterbacks, and injury reports."

Caveats: The moneyline's book and timing are unknown and it is probably close to closing,
so this is not a T-24h comparison. The 2024-2025 holdout was not touched. A known defect in
the sensitivity diagnostic (200 repeat counts truncated by one draw) changes no flags; it is
disclosed in the report and was not rerun.

## 2026-10-09: QB-001 backup-QB flag beats frozen Elo (development evidence)

Result: Elo+flag beat frozen Elo on the pre-registered test (prereg 75d1b8b, run
qb001-backup-flag-v1, code 8f55d54). On 2015-2023 all games, the Brier difference was
-0.00165, 95% CI [-0.00333, -0.00096]; log loss -0.00398. Better in 8 of 9 seasons.
It closes about 15% of Elo's gap to the historical moneyline. The moneyline is still
better by +0.0092 Brier, 95% CI [+0.0067, +0.0123].

Predictions vs actual: I predicted it would pass (it did), a 0.005 gap reduction (actual
0.0017), a 5-point penalty (chosen: 2, picked on 2006-2014 only) and a 20% flag rate
(actual 35.9%).

Weeks 1-4: the flag fires in 55% of early-season games but gains almost nothing there
(-0.0001). Later weeks carry the gain (-0.0021).

Why the penalty came out small (my words): "The QBs that are flagged in the earlier
season are rookie QBs that haven't played the season prior. They get flagged even though
they might make the team better."

Review note (from Claude): The same goes for new starters from trades and free agency.
One penalty had to cover
real backups and new starters, which likely explains why it came out small. QB-002 tests
this.

Caveats: The actual starter is known after the fact, which is mild lookahead at T-24h.
This is the second test on 2015-2023, so it is development evidence, not a final test.
The flagged-only summary was not pre-registered. New starters are flagged for their first
4 games, not 3 as the prereg estimated; the rule was applied as written. CIs are
conditional on the chosen penalty.

## 2026-10-09: QB-002 new-starter split is a null result vs QB-001

Result: QB-002 did not beat QB-001 on the pre-registered test (prereg 10832a4, run
qb002-new-starter-v1, code 37c7ac3). QB-002 minus QB-001 Brier on 2015-2023, all games:
-0.00049, 95% CI [-0.00127, +0.00054]. QB-002 wins 5 of 9 seasons. The two are treated
as equivalent, and QB-002 is not claimed to be better.

The rule did what it was built to do. Weeks 1-4 flags fell from 55% to 15% of games, the
flag rate fell from 35.9% to 26.4%, and the chosen penalty rose from 2 to 3 points.
Weeks 1-4 Brier improved by 0.0008 against QB-001.

Against frozen Elo (not the primary test): -0.0021 Brier, 95% CI [-0.0041, -0.0009].
It closes about 20% of Elo's gap to the historical moneyline, vs 15% for QB-001. The
moneyline is still better by +0.0087, 95% CI [+0.0063, +0.0119].

Predictions vs actual: beats QB-001 (no), penalty 4 (chosen 3), flag rate 20% (26.4%).

Why it was a null result (my words): "Because the effect of a rookie quarterback did not
affect the games as much as we predicted."

Review note (from Claude): The rule changed a flag in about a tenth of test games (258 of
2,458). Because the two models also use different penalties (2 vs 3 points), their
forecasts differ in about a third (790). The per-game differences are small and point
both ways (QB-002 wins 5 of 9 seasons), so the test could not separate them.

Caveats: This is the third test on 2015-2023, so it is development evidence only. The
run's wall-clock time (1h51) included the Mac sleeping; CPU time was about 25 minutes.
Results are unaffected.

## 2026-10-11: T-24h feasibility audit and frozen development rules

My words: "I just want it to be a good prediction model."

### Decisions

1. Timing validity covers every feature, not just QB inputs. A test is "T-24h valid" only
   if every input, including how it was built, was knowable at the forecast time. Tests
   using actual starters are "starter-known, exploratory." Tests using model-based
   metrics with undocumented training seasons are "exploratory."

2. Expected starter rule (same for backtests and live):
   - Start with the usual starter (QB-001 definition: most starts in the team's last 8
     games, prior games only).
   - If his final injury status is Out or Doubtful and was last modified before the
     cutoff, the expected starter is the team's other QB with the most dropbacks in its
     last 8 games. If there is none, use the rookie prior.
   - If the status is missing, has no date_modified, or was modified after the cutoff,
     the expected starter is the usual starter.
   - Live: Thursday games, early Thanksgiving games, and any game whose cutoff comes
     before the final report use the usual starter.

3. Metrics for confirmatory tests are model-free only: ANY/A for QBs; yards per play,
   yards-based success rate, sack rate and turnovers for teams. nflverse EPA, success
   (defined as EPA > 0), CPOE, xpass, WP and vegas_wp are exploratory only.

4. Data revisions: box-score stat corrections are disclosed, not disqualifying. Model
   refits make a metric exploratory. Every run records a SHA-256 hash of each input file.

5. Rookie prior is rolling: built only from QBs who debuted before the forecast season.
   QBs whose first dropback in the data is in 1999 are excluded from the prior.

6. Development budget: at most 3 tests, in this order: QB-003 (QB quality), team
   efficiency, schedule/venue. Each is tested on top of the combination accepted so far,
   and that comparison is frozen before the run.
   - Screening is walk-forward: tune on seasons 2010 through s-1, predict season s, for
     s = 2013 to 2023.
   - Include a feature only if mean Brier improves by at least 0.0005 versus the current
     best AND it is better in at least 6 of 11 seasons. Otherwise it is excluded as null.
     Worse on average is excluded and reported as harmful.
   - Two nulls in a row ends the budget. This is a budget limit, not proof that no
     improvement exists.

7. Final evaluation, pre-registered before the 2024-2025 holdout is opened:
   - v1 versus frozen Elo. Pass means the paired Brier CI is entirely below 0.
   - Encompassing test: fit market-only and market-plus-model logistic regressions on
     development data only, then compare their held-out Brier and log loss on 2024-2025
     with paired CIs. Historical moneyline timing is unknown, so this is exploratory.
   - The report states whether the result is T-24h valid or starter-known.
   - Pass: v1 becomes the candidate live model. Fail or inconclusive: v1 may run live as
     experimental, and frozen Elo stays primary.
   - Live deployment requires every input to exist at forecast time. The forecast job
     saves its own timestamped copy of each input it uses.

8. Corrections to earlier documents:
   - RESEARCH_PROTOCOL.md section 2 says T-24h is before injury reports are out. That is
     wrong for most games: final QB statuses were usually published 1 to 4 days before
     kickoff. A dated note goes under Changes on main later. Definitions do not change.
   - QB-001 and QB-002 are starter-known, exploratory results. Calling the actual-starter
     lookahead "mild" was wrong: in TEN 2023 weeks 8-9 the starter was QB3 on the weekly
     depth chart.

### Review note (from Claude)

Audit evidence (read-only, 2026-10-11): nflverse injury date_modified was checked for
2010-2023 QB rows. 1,489 dated rows for 2010-2022 (2023 counted separately, all before
the cutoff); 4 were modified after the cutoff and 4 had no date. 2009 has no dates and is
excluded. Depth charts before 2025 have no dates, so the replacement QB comes from
play-by-play instead. date_modified is the last edit, so a last edit before the cutoff
shows the final status existed by then, if the source's timestamps are accurate. nflverse
refreshes injuries too late for Thursday games live. Full output is in /tmp/forecast-audit/
(not committed).
