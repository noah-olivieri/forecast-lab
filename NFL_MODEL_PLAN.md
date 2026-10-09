# Forecast Lab: NFL matchup and score-distribution model

Draft research and implementation plan · 2026-10-08

## Objective and scope

Build a model that learns from prior NFL games, predicts player and team performance in an upcoming matchup, and produces a joint distribution of final scores. Derive win, tie, spread, and total probabilities from that same distribution. Test whether those forecasts improve on frozen Elo, simpler score models, devigged sportsbook probabilities, and prediction-market prices available at the forecast cutoff.

The deliverable includes two connected dashboards: a pre-game matchup and factor-contribution dashboard, and a post-game prediction-versus-results dashboard. A research-results view supports both.

Success is measured on unseen games and then prospective forecasts. Beating markets is a research objective, not a promised outcome. Exact-score hit rate is a secondary diagnostic; good probability distributions matter more than guessing one score exactly.

This document specifies future work. It does not activate jobs, replace models, authorize purchases, or change existing forecasts. Paper trading only. Preserve `elo-538-default-v0`, `home-rate-v0`, their golden tests, and existing forecast CSVs.

## 1. Forecast contract

Primary cutoff: T-24h before kickoff. T-1h can later be a separate experiment and model/horizon record. Define allowable automation delay and snapshot freshness in the research protocol before live rollout; label the actual horizon rather than silently calling a late forecast T-24h.

For each game publish:

- Expected and median points for each team, plus a representative feasible scoreline.
- Joint score distribution, selected likely scorelines, margin and total distributions.
- Home-win, away-win, and tie probabilities; spread cover/push and total over/push probabilities.
- 50%, 80%, and 95% predictive intervals, plus a joint-score uncertainty display.
- Predicted possessions, plays, pass rate, efficiency, sacks, turnovers, and scoring opportunities.
- Selected player volume, efficiency, and production distributions, conditional on expected availability.
- Data freshness, missing factors, expected lineup scenarios, forecast cutoff, model version, training cutoff, code SHA, input manifest, and simulation seed.

Display an expected score such as 24.6–21.8 separately from a feasible scoreline such as 24–21. Define overtime, tie, push, and settlement treatment per venue and contract. A forecast's YES probability must match that contract's payoff rules.

## 2. Data feasibility comes first

Create a source-and-field inventory before promising a feature. For every field record coverage by season, missingness, definition changes, retrieval method, publication latency, licensing/attribution, and whether availability at a historical T-24h cutoff is demonstrable.

Use three explicit eligibility labels:

1. **Eligible:** information demonstrably available before the forecast cutoff.
2. **Reconstructed historical:** derived from retrospective data with availability limitations. Report separately and do not call this a strict point-in-time test.
3. **Unavailable:** excluded from the forecast; visibly missing in the dashboard.

Initial sources and limitations:

| Source | Intended use | Constraint |
|---|---|---|
| nflverse schedules and play-by-play | Results, drives, plays, situational performance, schedule | Audit actual seasons and revisions; closing lines and observed weather are not T-24h predictors. |
| nflverse player/team stats, rosters, snap counts | Player production, participation history, identity mapping | Audit actual update times and field coverage. |
| nflverse Next Gen Stats / advanced stats | Passing, receiving, rushing and pressure measures | Verify each field and its publication latency; aggregate stats are not full tracking data. |
| FTN charting through nflverse | Motion, play action, screens, RPOs, blitzers, pass rushers, other charted events | Dictionary documents 2022 onward; availability and season-specific completeness must be audited. |
| nflverse participation | Personnel, formations, coverage labels, players on field | Fields exist, but coverage varies. From 2023 onward the public dataset is released after the postseason, preventing current-season updates through this feed. |
| Timestamped depth charts, injuries, transactions | Expected starters, participation scenarios | A date or game-week label alone does not prove information existed at T-24h. Audit historical archives and verify current feed health. |
| Archived weather forecasts | Wind, temperature, precipitation | Forecasts issued before cutoff only; observed game weather is an outcome/diagnostic. |
| Sportsbook odds archive and existing venue snapshots | Same-time probability benchmarks | Verify timestamp, paired sides, contract rules, and book. Closing lines are a separately labeled later-information benchmark. |
| Optional richer charting/tracking source | Fronts, protection, full route concepts, disguise, assignment detail | Candidate only after access, schema, latency, cost, and rights are verified. |

Verified documentation:

- [nflverse data schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html): participation publication delay, differing feed schedules, and statistical revisions.
- [Participation dictionary](https://nflreadr.nflverse.com/articles/dictionary_participation.html): personnel, formations, pressure, route, man/zone, and coverage fields.
- [FTN charting dictionary](https://nflreadr.nflverse.com/articles/dictionary_ftn_charting.html): the smaller charting field set and retrieval timestamp.
- [Participation source and attribution](https://nflreadr.nflverse.com/reference/load_participation.html).

Do not equate a coverage shell with a defensive front, personnel with assignment, or the primary receiver's route with the full offensive concept. Do not infer a detailed label from a result and present it as observed scheme data.

Keep broad-history and rich-charting cohorts separate. Compare models on identical games within each cohort; never mistake different eligible seasons for feature improvement.

## 3. Candidate factor registry

Register definitions before testing. All rolling windows, decay rates, interactions, and transformations are candidate choices selected using development data only.

| Group | Factors to test | Predicted outcomes affected |
|---|---|---|
| Overall strength | Frozen Elo; opponent-adjusted offense/defense; season and home advantage | Scores, margin, win probability |
| Passing offense | EPA/dropback, success, completion above expectation, air yards, explosive passes, sack avoidance | Passing efficiency, sacks, scoring |
| Rushing offense | EPA/rush, success, explosive runs, short-yardage conversion, QB rushing | Rushing efficiency, drive survival |
| Passing defense | Pass efficiency allowed, explosive passes allowed, pressure, sacks, coverage tendencies | Opponent passing and scoring |
| Rushing defense | Run efficiency allowed, box counts, run personnel, short-yardage defense | Opponent rushing and scoring |
| QB | Expected starter, rolling quality, pressure response, sack tendency, depth/accuracy profile, mobility | Passing/rushing outcomes, turnovers |
| Receivers/TEs | Expected usage, targets, depth, separation where available, yards after catch, drops | Target allocation, receiving production |
| RBs | Expected carries/targets, efficiency, receiving role | Rushing/receiving production |
| Offensive line | Continuity, expected availability, pressure allowed, run blocking proxies | Pressure, sacks, rushing |
| Defensive personnel | Available pass rush and coverage players, snap shares, substitutions | Pressure and coverage effectiveness |
| Offensive scheme | Personnel, formation, motion, play action, RPO, screens, run/pass selection, tempo | Calls, efficiency, possessions |
| Defensive scheme | Base/nickel/dime, fronts if charted, coverage, blitz/rush mix, disguise if charted | Calls, pressure, completion/explosive rates |
| Situational play | Down/distance, field position, score/time, red-zone and third/fourth-down behavior | Play selection, drives, scoring |
| Coaching | Coordinator changes, fourth-down decisions, pace, substitutions and tendency changes | Calls and game dynamics |
| Special teams | Field goals by distance, punts, returns, kickoff outcomes | Field position and points |
| Schedule/environment | Rest, bye, short week, travel/time zones, roof, surface, forecast weather | Efficiency, pace, kicking |
| Uncertainty/stability | Sample size, roster turnover, stale inputs, missing labels | Shrinkage and prediction intervals |

Treat turnovers, fumble recovery, defensive scores, and small-sample red-zone results as noisy. Test shrinkage toward appropriate league/player/team priors instead of assuming recent rates persist.

Estimate player quality separately from opportunity: 100 receiving yards on 15 targets differs from 100 on 5. Adjust for opponents, situation, scheme, and available teammates where identifiable. Avoid claiming that aggregate production uniquely identifies an offensive lineman's or defensive back's quality.

### Extended factor catalog

The catalog is deliberately broad. Every entry is a research candidate, not a requirement to force it into the final model. Give each candidate an explicit feature ID, definition, denominator, publication cutoff, source, missing-data policy, hypothesis, experiment ID and status: planned, unavailable, tested/rejected, or retained. Add newly identified factors through the same registry; this catalog cannot enumerate every possible influence.

| Family | Detailed candidates | Data and testing requirements |
|---|---|---|
| Individual receiving matchups | Expected receiver–corner assignments; slot/outside alignment; shadow coverage; size/speed profiles; route-specific separation and success; contested catches; coverage leverage | Charted assignments or tracking required for direct matchup claims. Model assignment probabilities, including rotation; compare with position-group baselines. |
| Pass protection and rush | Tackle/edge and interior matchups; line combinations; protection slides; chips; blitz pickup; stunts/twists; rush lanes; pressure timing; quick pressure versus coverage sacks | Verify assignment labels. Separate rush production, protection, QB time-to-throw and play design; test whether detail adds value beyond aggregate pressure. |
| Run design and blocking | Inside/outside zone; gap/power/counter; pulling blockers; run direction; blocking numbers; tight-end contribution; option reads; defensive gap integrity | Detailed concepts require charting. Separate observed labels from proxies; test concept × front/box × available blockers with partial pooling. |
| Tackling and pursuit | Missed tackles; yards after contact/catch; pursuit angles; tackling opportunities; defensive containment | Require reliable opportunity denominators and charting/tracking; distinguish player skill from opponent, space and scheme. |
| Secondary coordination | Coverage handoffs; communication errors; busted assignments; rotations; safety help; disguise; contested versus open targets | Direct labels require charting or documented annotation. Do not equate every explosive completion with a coverage bust. |
| Health and recovery | Public injury type/severity; recovery duration; practice participation; expected restrictions; returning players; illness; rehabilitation uncertainty | Timestamped public information only. Treat unknown severity as unknown; do not infer private medical facts. Test calibrated participation/limitation scenarios. |
| Workload and depth | Recent snaps, carries/routes and cumulative workload; consecutive high-snap games; rotation quality; backup readiness; replacement depth; unit combinations | Workload is observable; fatigue is a hypothesis. Adjust for role and game situation; test incremental value rather than assuming workload causes decline. |
| Execution and ball security | Fumbles and recovery separately; interception-worthy throws; dropped interceptions; strips; bad snaps; exchange errors; drops; blocked kicks | Audit event labels and small samples. Separate event generation from recovery/conversion luck and shrink rare outcomes. |
| Penalties and officiating | Team/player penalty type and rate; discipline; protection-related holding; coverage-related interference; pre-snap errors; accepted/declined/offsetting penalties; crew tendencies | Assigned crew must be known by cutoff. Adjust for teams, play type and era; test crew effects separately and with uncertainty. Never interpret association as favoritism. |
| Coaching adaptation | Opponent-conditioned game plans; protection and coverage changes; halftime shifts; tendency breaking; aggressiveness; substitution response; coordinator continuity | Learn adaptation patterns from prior games. Future adjustments are simulated probabilities, not known calls. Compare adaptive and fixed-strategy models. |
| Clock and possession strategy | Two-minute offense; end-of-half possessions; timeout usage; hurry-up/slowdown; prevent defense; fourth downs; two-point decisions; onside attempts; overtime decisions | Version applicable rules; condition on simulated state and available personnel. Test decision models and resulting score distributions. |
| Field-position feedback | Punt quality; return decisions; touchbacks; kickoff placement; penalties; turnovers; short fields; defensive/special-teams scores | Explicit possession transitions and accounting. Avoid counting a turnover's field-position benefit twice. |
| In-game availability changes | Probability of injury/exit; substitution; ejection; equipment issues; backup insertion and resulting strategy changes | Fit only where event labels support it. Sample uncertain exits using eligible historical rates; never feed future actual exits into the original forecast. |
| Environment and logistics | Altitude; wind speed/direction/gusts relative to stadium orientation; precipitation; temperature/humidity; forecast field condition; roof uncertainty; crowd noise; travel timing; time-zone acclimation | Archived forecasts and documented pre-game logistics required. Attendance, roof or field conditions unknown at cutoff become scenarios; observed values are diagnostics. |
| Roster and team continuity | Trades; signings; offensive-line combinations; QB–receiver continuity; new scheme familiarity; rookies; role changes; replacement quality | Timestamped transactions and participation history. Test hierarchical priors for new players/teams and uncertainty after structural changes. |
| Era and rules | Scoring environment; schedule format; kickoff/overtime changes; officiating emphasis; season-specific home advantage | Use rules effective for each game; fit historical era effects without inspecting future outcomes. Monitor transfer across regimes. |
| Stakes and incentives | Public playoff/elimination status; mathematically defined standings stakes; known resting-starter plans; divisional familiarity; rematches | Use information known at cutoff. Vague 'motivation', 'revenge' and 'momentum' narratives earn no arbitrary weight; test measurable proxies and log failures. |
| Preparation and scouting | Rest opportunity; opponent familiarity; prior coach/team connections; scheme changes; bye preparation; practice availability | Verify objective observations and timestamps. Avoid assuming access to private game plans or film-study effort. |
| Measurement quality | Label disagreement; provider changes; missing charting; corrected stats; identity/assignment ambiguity | Record quality flags, audit samples, test sensitivity across providers/definitions, and widen uncertainty or exclude unsupported detail. |

For sensitive or poorly observed influences such as personal circumstances, internal morale or private preparation, use no speculative player-specific features. Unmeasured variation belongs in uncertainty unless a legitimate, timestamped, reproducible observation supports a registered hypothesis.

### Skill, randomness and unforeseen events

Use separate mechanisms for persistent strength, opportunity, game-level shocks and rare events. Test whether additional distributions for turnovers, injuries/exits, defensive scores and kicking improve calibration and tails. Do not claim we can predict the timing of a freak injury or a fortunate bounce.

Register the probability of an event separately from its consequence: an offensive fumble, the recovery team, return yards and resulting field position are different outcomes. Define accounting for penalties, return scores, safeties and unusual plays before evaluating the simulator.

## 4. Matchup interactions to test

Pre-register the following families, then select a limited subset within development folds:

- Offensive personnel versus defensive personnel.
- Passing and receiver profiles versus man/zone and coverage families.
- Protection and QB pressure response versus pass rush/blitz mix.
- Motion, play action, screens, and RPOs versus relevant defensive tendencies.
- Run profile versus front/box counts and run-defense strength.
- Explosive offense versus explosive-play prevention.
- Red-zone tendencies versus red-zone defense, with strong shrinkage.
- Tempo versus defensive substitutions and available depth.
- Weather versus passing depth, kicking distance, and offensive strategy.
- Injury/lineup changes versus the specific opposing unit.
- Coaching changes versus historical tendency stability.
- Receiver alignment/route profiles versus likely individual coverage assignments and safety help.
- Protection combinations/chips versus edge/interior rushers, stunts and pressure timing.
- Run concepts/blocking personnel versus fronts, box counts and gap responsibility.
- Workload/rotation depth versus tempo, altitude and long drives.
- Tackling/containment versus yards-after-catch/contact profiles and mobile quarterbacks.
- Injury limitations and replacement combinations versus opposing schemes.
- Crowd/noise conditions versus communication, cadence and pre-snap penalties.
- Wind direction and stadium orientation versus pass direction/depth and kicking.
- Penalty tendencies and assigned crews versus play types and offensive/defensive style.
- Late-game strategy versus score, timeouts, possession and applicable overtime rules.
- Coordinator/roster changes versus the relevance of older matchup history.
- Expected exits/substitutions versus backup quality and adaptation.

Condition call frequencies on situation. A defense facing third-and-long often will naturally show different packages from one facing first down; raw package win rates would confound these contexts.

Model both expected usage and effectiveness. An offense performing well against Cover 3 matters only to the extent it is likely to face Cover 3. Pool sparse combinations with league/team/player priors rather than treating five successful plays as reliable evidence.

## 5. Model architecture and progression

Maintain two research lanes:

- **Independent football model:** excludes market prices from predictive inputs; tests whether football data independently predicts outcomes.
- **Market-assisted challenger:** may use prices captured at the same cutoff; must improve over those prices on unseen games. Report separately.

Model progression:

1. Frozen Elo/home-rate and simple historical score baselines.
2. Regularized, opponent-adjusted team score/margin/total model.
3. Player availability, usage, and performance components.
4. Conditional scheme-choice and matchup-effectiveness components.
5. Drive simulator, then play simulator if it adds verified value.
6. Ensemble of useful components; weights and calibration learned within development folds.

Compare regularized regression/additive models, hierarchical models, and boosted-tree challengers. Neural networks are a later candidate requiring sufficient reliable data and improvement over simpler alternatives. Do not select an architecture solely because it is more complicated.

The detailed simulator follows:

Expected lineup scenarios → initial possession/field position → offensive choice → defensive response → play outcome → clock/field position/down update → drive outcome → next possession → final regulation/overtime result.

Submodels predict call probabilities, assignments where supported, yards and completion outcomes, pressure/sacks, penalty types and enforcement, turnover generation/recovery/returns, drive continuation, kicks, player involvement, exits/substitutions and adaptive strategy. Share game-level pace/strength uncertainty so opposing scores are not sampled as unrelated independent quantities.

Use jointly learned offensive/defensive responses to predict tendencies, rather than pretending we can perfectly reproduce a coach's counter-strategy. A coverage label observed after a play can train historical labels; the future game's actual coverage or pressure outcome cannot be used as a pre-game input.

Player projections and team projections must agree: receptions cannot exceed completions, team yards reconcile with player allocations under defined accounting rules, and possessions/plays consume time. Do not independently predict every player stat and simply sum contradictory totals.

Start with roughly 10,000 simulations per game as a candidate, then measure convergence. Increase simulation count until Monte Carlo error is acceptably small relative to model uncertainty; extra simulations do not fix a bad model.

## 6. Historical learning without future information

Use 2006–2023 as the initial broad development target where data supports it; audit coverage before selecting the final start year. Leave 2024–2025 locked for final evaluation, following the existing feature proposal. Rich-charting models have a shorter development window and must report that limitation.

For each historical game:

1. Set its forecast cutoff to kickoff minus 24 hours.
2. Select only observations published/available before that cutoff.
3. Derive rolling features using completed eligible prior games and the established FINISH_LAG.
4. Fit only on earlier resolved training games; predict the held-out next period.
5. Save the forecast before loading that game's labels into the evaluation path.
6. Compare with results; use them for later training only.

Outer evaluation proceeds chronologically by season; inner chronological folds select windows, regularization, architectures, calibration, and ensemble weights. All plays from a game stay together. No random play-level split across training and test sets.

Fit preprocessing, opponent adjustments, feature selection, imputation, scaling, and attribution background sets on training data only. Audit whether supplied EPA/expected-points features were trained using future seasons or market information; recompute eligible measures or disclose reconstructed research where necessary.

A daily snapshot archive is required for strict live and future historical reconstruction. Pin source artifacts and hashes. Retrospective statistical corrections and end-of-season charting releases must be accounted for explicitly; a game having happened earlier does not establish that today's corrected dataset was available then.

Freeze every development choice before opening the final holdout. Evaluate the holdout once; later model revisions require a new prospective test or a newly reserved evaluation period. Current Elo characterization fixtures containing 2025 synthetic games do not constitute inspection of real holdout outcomes.

## 7. Planned experiments

Every experiment gets an ID, hypothesis, eligible cohort, data/code hashes, training/evaluation cutoffs, primary metric, baseline, tuning budget, and keep/reject decision. Log unsuccessful trials too.

| Experiment | What changes | Evidence required |
|---|---|---|
| Recalibration | Calibrated Elo versus frozen Elo | Probability improvement on held-out seasons |
| Efficiency | Opponent-adjusted offense/defense versus ratings baseline | Better score/margin errors and distributions |
| Recency | Candidate rolling windows, decay and offseason carryover | Stable improvement across chronological folds |
| Players | QB first, then other units | Incremental improvement beyond team efficiency |
| Opportunity | Volume models versus raw player averages | Better player distributions and coherent team totals |
| Availability | Probabilistic lineup scenarios versus single lineup | Better calibration and uncertainty |
| Schemes | Tendencies and interactions versus player/team model | Same-cohort improvement beyond existing strength |
| Situational | Context-conditioned models versus raw tendency rates | Better call/outcome prediction and final scores |
| Coaching/context | Coaching, schedule, travel, weather and special teams | Incremental value and stable estimates |
| Simulation depth | Direct score, drive and play models | Better score distribution, not just complexity |
| Model family | Regularized/additive, hierarchical, tree and later neural variants | Fixed-budget chronological comparison |
| Ensemble | Learned combination versus best component | Held-out improvement without calibration loss |
| Market lane | Independent and market-assisted variants | Same-time market comparison, reported separately |
| Robustness | Missing feeds, stale data, new QB, early season, neutral games | Graceful uncertainty/fallback and transparent flags |

For each component perform both add-one and remove-one ablations. Removing a group requires refitting on the same training data, not merely setting inputs to zero. Use correlated feature groups for importance analysis. Record all repeated tuning to acknowledge selection effects.

### Additional experiment families

- Individual assignments versus position-group matchup models, evaluated on identical games.
- Protection/rush and run-concept interactions versus simpler pressure/rushing models.
- Health, restrictions, workload and replacement depth versus availability-only models.
- Adaptation and clock strategy versus fixed tendencies, including halftime and late-game behavior.
- Penalty/crew terms versus team-and-situation penalty models.
- Turnover skill versus recovery/conversion luck; rare-event and heavy-tail alternatives.
- Field-position transitions and special-teams detail versus average starting-field-position models.
- Environmental detail versus basic weather/roof/rest terms.
- Era/structural-change adaptation versus fixed historical carryover.
- Objective stakes/familiarity variables versus context-free models; log rejected narrative proxies.
- Label-quality, publication-delay and provider sensitivity on common eligible cohorts.

Each family follows nested chronological selection, add/remove ablations, sample-size reporting, and paired out-of-sample comparison. A large registry increases the risk of finding lucky improvements. Limit tuning budgets, report all trials, and reserve independent evaluation rather than treating nominal significance after extensive searching as confirmation.

## 8. Metrics and presentation of results

Pre-register a primary score-distribution metric and a primary probability metric before experiments. Proposed choices: CRPS for margin/total distributions and log loss for resolved contract outcomes. Joint-score energy score, Brier score and mean absolute errors are supporting metrics.

| Output | Evaluation |
|---|---|
| Team scores | MAE, RMSE, signed bias, empirical interval coverage and widths |
| Margin/total | MAE/RMSE, CRPS, quantile loss, coverage, distribution calibration |
| Joint scores | Energy score, feasible-score checks, score correlation, tail outcomes |
| Winner/contract probabilities | Log loss, Brier, calibration/reliability plots with counts |
| Ties and pushes | Explicit multinomial or settlement-specific evaluation; no silent exclusion |
| Player production | MAE/RMSE, bias, quantile loss and interval coverage by stat/position |
| Calls/packages | Log loss, Brier, frequency calibration; rare-class diagnostics |
| Play/drive outcomes | Distribution errors, conversion calibration, turnover/sack/scoring calibration |
| Market comparison | Paired metric differences on common games/contracts and cutoffs |
| Paper returns | Bid/ask-based fills, fees, capped size, gross/net P&L, drawdown, counts |

Score actual integer outcomes against the saved distributions. Do not force 0/0.5/1 game labels onto contracts with different settlement rules. Pre-register any binary tie convention; prefer explicit three-outcome game probabilities where practical.

Devig paired sportsbook sides using a documented method and test sensitivity to the method. Where three-way markets or push/refund rules apply, align probabilities first. Spread/total line prices alone do not uniquely determine a full score distribution; do not invent sportsbook score probabilities from one line.

Report same-time T-24h comparisons as primary. Closing odds appear only in a labeled later-information benchmark. Historical Kalshi/Polymarket coverage may be much shorter than sportsbook history; do not imply market comparisons exist for all historical seasons.

Show pooled and per-season results, plus predeclared slices: early/late season, favorite/underdog, neutral site, backup QB, weather, short rest, and missing data. Show sample sizes. Bootstrap paired comparisons in chronological blocks such as weeks, with season-level sensitivity; thousands of plays are not thousands of independent final-score forecasts.

Separate historical backtest, reconstructed research, final holdout, and prospective live results. Favor calibrated, repeatable gains over one profitable streak. Promote a component only when improvement is reasonably stable, uncertainty is disclosed, data is live-eligible, and operational cost is justified.

## 9. Dashboard A: pre-game matchup and factor contributions

### Game overview

Team selector, game/date, horizon, model version, training cutoff, immutable forecast link. Show expected score, feasible scoreline, score heatmap, margin/total distributions, win/tie probabilities, intervals, same-time market probabilities, and data-quality badges.

### Matchup matrix

Show offense versus opposing defense for pass, run, pressure, personnel, coverage and situational groups. Each cell includes expected usage, predicted effectiveness, opponent-adjusted historical estimate, shrunk estimate, sample size, interval, and source freshness. Unavailable labels appear as unavailable.

Filters: down/distance, personnel, formation, coverage family, red zone, recent window and selected player scenario. Show both directions: home offense versus away defense and away offense versus home defense.

### Detailed matchup and reliability panels

Add receiver–coverage assignment probabilities, protection/rush combinations, run-concept matchups, health/workload/depth, penalties/crew, adaptation/clock strategy, and environment panels as their data becomes eligible. Each panel links to factor IDs, source quality, sample counts and supporting experiments.

Provide an expandable complete factor catalog, including rejected and unavailable factors, so absence is explainable. Display uncertainty due to sparse evidence separately from ordinary game variability where estimable. Label direct observations, charted judgments and proxies distinctly.

### What moved this game's forecast?

A waterfall begins at a defined baseline prediction and adds attributed contributions to expected points, margin, total, or win probability. User chooses the output; units are points or probability points, not unlabeled percentages.

For additive models, contributions can come from fitted terms. For nonlinear models or simulators, use a documented grouped attribution method with a training-only reference and allocation of interaction effects. Include baseline and residual/interaction contributions so displayed bars reconcile to the selected prediction. Use paired simulation seeds for scenario comparisons.

Each factor card shows:

- This game's raw feature value and standardized value where applicable.
- Model coefficient for an interpretable component, or nonlinear effect description.
- Local forecast contribution and uncertainty/stability where estimable.
- Global held-out ablation/permutation importance, with metric units and intervals.
- Historical sample count and whether it uses direct charting or a proxy.

Keep local contribution, fitted coefficient, and out-of-sample usefulness distinct. There is no single permanent percentage weight for a nonlinear factor; effects depend on the matchup and output. Overlapping QB, protection and offensive-efficiency factors must not each receive full credit for the same evidence.

### Lineup and scenario explorer

Toggle plausible QB/injury/weather/package scenarios and show changes in scores, probabilities, player outputs and uncertainty. These are labeled sensitivity analyses. They do not edit the logged forecast or establish causal effects.

### Player projection table

Expected starter/participation probability, expected snaps/opportunities, production median, intervals, relevant matchup and data reliability. Show uncertainty for backups, rookies and players changing roles.

## 10. Dashboard B: post-game forecast versus actual performance

### Frozen prediction versus result

Display the original pre-game forecast unchanged beside final scores. Show team score errors, margin/total errors, interval inclusion, probability scores, and market comparison. An updated model's retrospective prediction never replaces the original.

### Stat reconciliation

| Stat | Pre-game predicted value | Prediction interval | Actual value | Error | Reliability/sample |
|---|---|---|---|---|---|
| Possessions, plays, pass rate | Saved projection | Saved bounds | Observed | Signed/absolute | Source |
| Pass/rush efficiency, yards, explosive plays | Saved projection | Saved bounds | Observed | Signed/absolute | Source |
| Pressures, sacks, turnovers | Saved distribution | Saved bounds | Observed | Error and distribution score | Source |
| Red-zone trips, scoring drives, kicking | Saved projection | Saved bounds | Observed | Signed/absolute | Source |
| Player snaps, targets, carries, yards | Saved projection | Saved bounds | Observed | Volume and efficiency errors | Source |
| Defensive package/coverage usage | Predicted mixture | Uncertainty | Charted mixture | Distribution difference | Pending if delayed |

Aggregate each statistic using the same definition in prediction and actual evaluation. Show predicted opportunity separately from efficiency so a wrong snap/target estimate is not blamed entirely on player quality.

Pre-game inputs such as prior-eight-game EPA have no identical same-game 'actual' feature counterpart. Display that historical input alongside the distinct predicted in-game outcome and observed in-game outcome; never pretend they are the same measurement.

### Expanded outcome reconciliation

Add the following rows when observed data supports them:

- Actual receiver–coverage assignments, route usage, blocking/protection and rush combinations.
- Motion/play-action/RPO usage and first-half versus second-half call distributions.
- Tackles/missed tackles, drops, interception-worthy throws and recovery outcomes.
- Penalties by type and enforcement effect; pre-snap communication errors where charted.
- Starting field position, short-field possessions, return scores and kicking distance/outcomes.
- Injury exits, restrictions, actual substitutions and backup performance.
- Timeouts, fourth-down/two-point decisions, end-of-half execution and overtime.
- Observed weather/roof/field conditions versus the archived forecast/scenarios.

Show data-pending and label-disagreement states. A source published after the game can evaluate an outcome without becoming an eligible input to that game's prediction.

### Where did the forecast miss?

Use a diagnostic chain: availability → usage/calls → efficiency → drive outcomes → final score. Flag late injury news, unexpected pace, coverage surprises, pressure/sack misses, turnover swings, explosive plays and kicking outcomes.

Optional replay: rerun with one observed intermediate component substituted, holding the others fixed, to quantify model sensitivity. Label it hindsight diagnostic, not a valid pre-game forecast or proof that a factor caused the score error. Preserve an interaction/remainder category; correlated mechanisms cannot be cleanly assigned exact causal points from one game.

### Player review

Expected versus actual participation, opportunity, efficiency and production; interval coverage; unexpectedly good/poor performances. Include denominator context rather than ranking solely by raw yards or touchdowns.

### Evidence accumulated over many games

Factor groups show historical held-out usefulness, usage errors, outcome errors, calibration drift, sample counts and trends. One surprising game triggers investigation; it does not justify increasing a factor's weight by hand.

## 11. Research-results view and provenance

Both dashboards link to an experiment explorer: model versions, included factors, dataset cohort, trial history, ablations, metrics by season, calibration plots, confidence intervals, paired baseline comparison, and live/historical badges.

Persist separate immutable records for forecast inputs, score samples/distribution summaries, player projections, predicted intermediate stats, factor attributions and market snapshots. Link them using forecast/model/game/horizon IDs. Store actual outcomes and later corrections as separately versioned observations.

Proposed research tables: source_manifest, game/drive/play observations, player_identity, availability_observation, scheme_observation, feature_snapshot, training_run, experiment_result, game_prediction, player_prediction, factor_attribution, game_actual and diagnostic_run. Publication timestamps and fetch timestamps are distinct fields.

DuckDB/Parquet fit the existing project. Keep large raw artifacts in the existing ignored/data storage conventions; small published forecast proof stays in forecasts/. Extend the existing dashboard/site after inspecting it; choose its implementation during that phase rather than introducing a separate hosting system now.

## 12. Improvement and operational policy

Weekly parameter updates may use newly completed, published eligible games under a frozen training recipe. Record each parameter artifact and training cutoff. Structural changes to features, architecture or calibration require a new version and a fresh validation/promotion decision.

After each week:

1. Reconcile final results and available stats; mark provisional/corrected data.
2. Score saved forecasts without changing them.
3. Monitor group biases, calibration, interval coverage and missingness.
4. Retrain the existing recipe on eligible past data.
5. Evaluate proposed structural changes in development only.
6. Promote reviewed candidates based on the registered criteria; otherwise retain the incumbent.

A fallback can use the simpler independent model or frozen Elo when charting/player feeds fail. Log which model actually produced a forecast. Never silently fill missing actual scheme labels with invented values.

## 13. Test requirements

Implement production changes through tests first. Keep synthetic tests free of network calls and secrets.

- Golden benchmark tests: frozen Elo/home-rate outputs unchanged.
- Future-mutation tests: altering later games, actual starters, injuries, weather, lines or charting cannot alter an earlier forecast.
- Availability boundary tests: late publications/corrections excluded; FINISH_LAG and T-24h boundaries enforced.
- Training isolation: transforms, player ratings, selection and calibration see training folds only; all plays in a game remain in one fold.
- Ingest integrity: IDs, aliases, duplicate plays, join multiplicity, missing/changed fields and revision history.
- Football accounting: regulation/overtime, penalties/no-plays, kneels, spikes, sacks, drives, scoring, clock and possession consistency.
- Player accounting: opportunities and production reconcile with team totals under explicit definitions.
- Sparse-data behavior: unseen player/package, rookies, coordinator changes and missing inputs produce shrinkage/uncertainty.
- Distribution tests: valid probabilities, coherent joint/marginal summaries, rare events and Monte Carlo convergence.
- Metrics: hand-checkable probability scores, CRPS/quantile calculations, ties/pushes, paired comparisons and reproducible block sampling.
- Market rules: correct sides, devig, timestamp matching, settlement, fees and simulated fills.
- Attribution/dashboard tests: units, contributions reconcile, no double counting in display, unknown fields and no pre-game exposure of actual outcomes.
- Persistence: append-only forecasts, provenance, re-run protection, per-game isolation and site parsing.

Additional checks for the extended catalog:

- Assignment uncertainty and combination identities; proxies must not render as observed labels.
- Rare-event generation/recovery/return accounting and no double counting of field-position effects.
- Accepted/declined/offsetting penalties, repeat downs and clock effects.
- Substitution/exit scenarios and player opportunity redistribution.
- Adaptive strategy uses simulated history, not the future actual sequence.
- Historical rules, environment and crew availability are selected as of the forecast.
- Provider/label uncertainty and unsupported factors remain visible through evaluation and dashboards.

## 14. Delivery sequence and acceptance gates

| Phase | Deliverable | Acceptance gate |
|---|---|---|
| A: live foundation | T-24h automation, settlement/scoring, archived input cutoffs | Reliable immutable forecasts and same-time comparisons |
| B: protocol/data audit | Registered objectives, feature registry, availability/coverage report | Clear eligible fields and locked evaluation sets |
| C: historical harness | Game/drive/play/player tables and chronological evaluation | Leakage tests and reproducible baseline report |
| D: score baseline | Opponent-adjusted score distributions and simple player opportunity | Improvements measured against simple baselines |
| E: players/context | Availability, QB, units, rest/weather/special teams | Incremental held-out evidence and coherence |
| F: schemes | Conditional call mixtures and selected matchup interactions | Same-cohort gains; explicit live-feed eligibility |
| G: simulation | Drive then play simulation; useful ensemble | Better distributions, stable calibration and valid accounting |
| H: dashboards | Matchup/contribution and post-game reconciliation views | Fully traceable saved predictions with honest attribution |
| I: final evaluation | Locked 2024–2025 test and frozen candidate | Report result once, including failures |
| J: prospective test | Candidate alongside Elo in the live pipeline | Ongoing accuracy, calibration and paper-return evidence |

Dashboard schemas and mockups can be designed during B–D; populate them with real saved outputs as components arrive. Do not wait for the most elaborate simulator to start gathering honest forecasts.

The first concrete build is the source inventory plus a small chronological score baseline. It establishes reliable inputs and evaluation before the scheme engine grows. The final ambition remains a detailed matchup model; complexity earns its place through measurable improvement.
