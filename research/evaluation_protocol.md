# NFL historical evaluation protocol

Draft foundation specification, 2026-10-08; reviewed choices must be frozen before
experiments. This does not amend `RESEARCH_PROTOCOL.md`, activate jobs or authorize
holdout access. Source limitations: [data inventory](data_inventory.md).
Candidates: [feature registry](feature_registry.csv). No candidate is selected by
being listed. No real 2024–2025 outcomes were inspected during this task.

## Forecast and cohort contract

Predict each regular/postseason game (exclude preseason) at exact historical
`as_of = kickoff_known_at_cutoff - 24h`, UTC-aware. Research does not relabel the
live automation's [K−24h, K−21h) window as an exact cutoff. A later live comparison
must replay at its saved actual capture timestamp and report actual horizon.
Reschedules require versioned schedule observations; without them, flag the
historical final kickoff as reconstructed. Missing times are exclusions with
counts/reasons, never imputed convenient kickoffs. Season denotes starting year,
including postseason played the following January/February.

Keep distinct, immutable cohort IDs:

- `strict_pit`: every selected input revision and derived-model artifact has
  evidence it was publicly available before cutoff. Our contemporaneous receipt
  can prove availability; a retrospective fetch alone cannot. Include only
  eligible prior results. If no historical games meet this gate, publish zero
  coverage, not reconstructed results under this badge.
- `reconstructed_scores`: final retrospective schedule/results with explicit
  assumed four-hour finish delay; corrections and schedule changes cannot be
  proven historical vintages. This is the first executable research cohort.
- `reconstructed_rich`: later charting/participation, with exact seasons and
  hindsight limitations. From-2023 same-season participation is research-only;
  a prospective counterpart must use released earlier-season data or omit it.
- `prospective`: actually archived pre-event inputs/forecasts. Never pool with
  historical reconstruction or the locked final test.

A strict prior game requires `kickoff + FINISH_LAG < as_of` (four hours, matching
existing behavior) **and** evidence of completed status/final score publication
and the selected revision's availability before `as_of`. Four hours alone is
not proof of completion of a delayed game. Each selected value needs source,
entity key, observation time, publication/first-seen time, revision ID, retrieval
time, artifact hash, and availability evidence. Unknown timestamps are unknown.
Do not stamp old observations with synthetic publication times in strict mode.
At the boundary, an observation available exactly at cutoff is excluded.
Post-game labels may use a separately pinned finalized version; future label
corrections must not overwrite saved forecasts or past feature snapshots.
For training or a residual available at cutoff, select the latest admissible
revision at that cutoff, not the evaluator's later finalized label. Preserve
the earlier fit/prediction and record which subsequent eligible label version
formed its residual. Unknown or date-only publication times cannot establish
a sub-day cutoff; timezone ambiguity must be rejected, not assumed UTC.

## Chronological splits and tuning

Broad development target: 2006–2023, conditional on a **through-2023** kickoff and
results completeness audit. These are planned seasons, not a completeness claim.
1999–2005 may initialize the frozen baselines under their existing recipe, never
score development claims. Avoid changing the start year after seeing performance.
If input coverage requires changing it, record a dated amendment before fitting.

| Role | Seasons | Use |
|---|---|---|
| Initial fit / warm-up | 2006–2011 | Fit new baseline; produce sequential residual history; no headline evaluation |
| Inner chronological validation | 2012 onward, strictly before the outer season | Select transforms, model choices and tuning |
| Outer development evaluation | Each season 2015–2023 | Train on earlier seasons; save predictions before joining labels |
| Final locked test | Season 2024 and season 2025, including their postseasons | One evaluation after complete recipe/manifest freeze and explicit later authorization |

For outer season Y, inner folds validate each year v in 2012..Y−1, trained on
2006..v−1. Training updates during v use only newly completed/published games at
each cutoff, following the same predeclared recipe; no future validation labels
enter a fit for an earlier forecast. Choose by mean per-game inner primary metric,
record per-year sensitivity, then refit on eligible data before Y. Outer Y must
not select its own recipe. Previous outer years may enter later years' training
and inner validation, as they would in chronological deployment; that does not
make nested results a new untouched holdout.

First score-model tuning budget: nine settings, ridge penalty {0.0003, 0.001, 0.003} ×
result half-life {365 days, 730 days, no decay}. Equal two-row game weights;
penalty defined on the mean weighted squared-error objective, so implementation
must document library rescaling. Among settings within 0.001 margin-CRPS points
of the minimum, prefer larger penalty, then no decay, then longer half-life.
Use candidate margin CRPS, not Brier or a comparator difference, for this choice.
No calibration,
additional feature search or ensemble tuning in this first experiment. Fixed
settings for distribution/residual generation below are not a hidden tuning grid.
Log all runs, failures and rejected variants. More architecture/feature searches
require an explicit development budget and new experiment IDs.

Rich history has much less development: participation 2016–2023, FTN charting
2022–2023. Do not force the broad split onto missing seasons or compare its pooled
score to a broad-history model. Predeclare chronological within-season folds for
2022 training / 2023 evaluation after coverage audit, preserving games and
publication lags. Such a small reconstructed cohort is exploratory and cannot
alone promote a scheme component. Apply common-game baseline comparisons.

Freeze final feature IDs/definitions, availability rules, start years, folds,
tuning budget and tie-breaker, chosen parameters, distribution/calibration recipe,
metrics, bootstrap blocks/seed, source/code/lockfile hashes and decision thresholds
before opening 2024–2025. The final runner must refuse those seasons by default.
No downloads, previews, summary stats, slice selection or errors revealing real
holdout outcomes during development. Even a seasons-filtered nflreadpy schedule
loader can retrieve the full holdout artifact; ingestion needs isolation first.

Final evaluation, when separately authorized, is a single sealed walk-forward
run across both years. Earlier resolved holdout games may update parameters for
later cutoffs under the frozen recipe, but never structure/hyperparameters.
Release reports only after the run finishes; do not tune after viewing 2024.
Revisions after that need a new prospective period, not another final-test claim.
Existing synthetic 2024/2025 tests are allowed and do not open this holdout.

## Frozen comparisons and outcomes

Replay `elo-538-default-v0`, `home-rate-v0` and `market-mid-v0` through the existing
functions without edits or recalibration. Record baseline replay start year,
source hash and eligibility policy. Candidate and baselines use the same vintage
and cutoff gates; Elo/home-rate may additionally replay the explicitly audited
1999–2005 warm-up, while the new score model starts in 2006. Report this fixed
history difference, not a retuned baseline. Keep published live CSVs and golden
expectations unchanged. If a strict source policy is added, filter reference
inputs in the new harness rather than changing frozen math. Also compare a
no-opponent league score distribution with the same home/neutral treatment and
training history, fixed no decay, and its own chronological residual estimates;
it has no tuning grid. Also include a fixed 0.5 probability comparator.
RF-001 compares whole recipes; a gain cannot be attributed solely to opponent
adjustment because the candidate also tunes recency. A later same-decay ablation
would be a separate registered test.
Elo has no native score distribution; do not invent one to score its CRPS.

For compatibility with the frozen research protocol, probability primary is
**Brier on home-result share**, y = 1 home win, 0 away win, 0.5 tie. A joint model
maps to `p_share = P(home > away) + 0.5 P(tie)`; this scalar is not literal
P(home wins). Secondary is fractional-label binary log loss (clip to
[1e−6, 1−1e−6], report clipping counts and unclipped extremes). Brier remains
unclipped. Report ties and separately score explicit win/away/tie predictions
with multiclass Brier/log loss where the model supplies them. Do not manufacture
a three-way Elo forecast. This research metric choice resolves the model plan's
suggested log-loss primary in favor of the existing frozen Brier convention.
It does not change saved live `p_yes` semantics or venue settlement rules.

Score-distribution primary: **margin CRPS in points**, home minus away. Total
CRPS is the key secondary, plus team-score MAE/RMSE/signed bias, paired joint-score
energy score, 50/80/95% interval coverage and width. A full score-distribution
promotion needs both margin and total evidence, not just a better mean score.
Exact score hits are diagnostic. For empirical draws x, CRPS is
mean(|x−y|) − 0.5 mean(|x−x'|); specify an exact sorted-sample implementation.
Use the empirical distribution V-statistic (all ordered draw pairs, including
diagonal zeros) consistently, not an unexplained switch to a fair-CRPS estimator.
Energy score uses the same form with Euclidean distance on the two-score vector,
with 10,000 independently sampled index pairs (sampling with replacement, using
a separate saved seed) for its second term; repeat with a second seed to report
approximation sensitivity. Use nearest-rank empirical quantiles at equal-tail
25/75%, 10/90% and 2.5/97.5%; coverage includes interval endpoints.
Report fixed-decile calibration/counts and discrete randomized PIT with saved
seed; do not choose bins to flatter outcomes. No player/simulator claims from
this first baseline.

Primary results include every eligible scheduled game; model failure is a
recorded failed prediction, not a silent drop. A predeclared league fallback
produces a scored forecast where sufficient eligible history exists. Publish
attempted/eligible/predicted/fallback/missed/excluded counts and reasons.
There is no numerical loss for an absent forecast. Identify metrics as
conditional on successfully predicted/fallback games and report eligible-cohort
coverage beside them. For Brier additionally bound the eligible-cohort average
by assigning each missed game's possible loss range (0..1 for win/loss labels,
0..0.25 for a half-tie label). Never present the observed subset mean as a complete
cohort score. Do not recommend promotion if any outer-evaluation game is missed;
fix operational coverage first without tuning on its outcome.
Compare candidate and baselines on identical game IDs/cutoffs/cohort/labels.
Market-complete subsets must also report full-cohort football scores and selection
coverage; never compare an all-game average to a market-subset average.

Same-time sportsbook tests require book, both sides, line/OT/tie/push rules,
snapshot and quote-update timestamps. Select latest snapshot at/before cutoff,
with no quote after cutoff and max age 30 minutes. For a snapshot earlier than
exact T−24h, replay every compared football model at that snapshot timestamp,
save the actual horizon and report this matched-snapshot cohort separately from
the exact-T−24h score cohort. Never give the model intervening news unavailable
to the compared price. Exact-T−24h market claims require an exact-time snapshot;
otherwise report the timing limitation. One predeclared book order
and no best-price cherry-picking; primary book unresolved until coverage audit.
Proportional devig: q_i = 1/decimal_odds_i, p_i = q_i / sum(q); specify a power
method sensitivity before running it. Two-way refunded ties identify conditional
non-tie probability, not p_share; compare on a labeled non-tie cohort or align
with an explicitly registered tie treatment. Spread/total prices on one threshold
do not identify a full score distribution. Missing odds stay missing. Closing
lines are a labeled later-information reference, never training inputs or a
substitute T−24h benchmark. A prediction-market test additionally requires its
actual settlement payoff, same-cutoff BBO and contract mapping. No P&L claim or
fee/fill model in this foundation.

## Paired inference, search control and leakage rules

For each comparator compute per-game candidate-minus-baseline loss on common
rows (negative favors candidate); report pooled and per-season means, sample
sizes and Brier skill with its denominator. Use 5,000 paired bootstrap replicates,
seed 20261008: order football weeks within each season, with REG weeks followed
by postseason rounds in kickoff order; game_type disambiguates overlapping week
labels. Sample noncircular contiguous four-week blocks uniformly over valid
start positions, concatenate and truncate to that season's original week count.
Keep all paired games/models in each drawn week; replicate game counts can vary.
Pool replicate per-game losses using their actual counts. Publish percentile
95% CIs (linear empirical percentile interpolation), plus one-week sensitivity
and whole-season resampling of the original seasons with replacement.
These intervals condition on saved predictions; they do not refit the models or
capture tuning/selection uncertainty. Weeks include postseason;
never treat plays, two team rows, duplicate venue rows or multiple thresholds as
independent games. Few seasons/sparse slices mean wide, unstable intervals.

Development improvement is evidence for further research, not proof of an edge.
For the first baseline recommend further work only if paired primary improvement
is negative pooled and in a majority of outer seasons without clear total-CRPS
or calibration deterioration; report uncertainty even if inconclusive. Do not
select a winner by nominal p-value after searching many candidates. Confirmatory
claims depend on the untouched final evaluation and prospective evidence. Failed
experiments stay in the ledger; later families need registered budgets and
multiplicity-aware interpretation, not retrospective significance stories.

Predeclare slices: early weeks 1–4 / later regular season / postseason, neutral,
rest <6 days, missing inputs, and season. Backup-QB/weather/favorite slices only
when defined using eligible pre-cutoff inputs, never actual starter or closing
line. Unknown slices retain an unknown category. No holdout-driven slice design.

All training and selection must obey:

1. Whole games stay in one chronological fold. The target game's scores/plays,
   actual starters, actual scheme, realized weather and closing odds are confined
   to a separate evaluator, joined only after forecasts are saved.
2. Fit imputation, scales, encodings, opponent adjustments, priors, player ratings,
   feature selection and attribution reference sets on eligible training history.
   No all-season means, future team effects, full-career player ratings or
   end-of-season roster membership. Unseen entities shrink to training priors.
3. Rolling observations require both game completion and field publication.
   A later correction never rewrites earlier predictions; reconstructed analyses
   name the pinned final-data assumption and test publication-delay sensitivity.
4. EPA, CPOE, xYAC, xpass and supplied ratings are learned outputs, not raw facts.
   Audit model training seasons, vintage, predictors and market inputs. Exclude
   from strict cohorts if unknown; rebuild an earlier-training-only artifact or
   label an exploratory reconstructed experiment. Leave all out of the first
   score baseline. Vegas WP and market-derived efficiency cannot enter the
   independent lane. A leave-one-season-out model can still use future seasons.
5. Later calibration uses chronological out-of-fold predictions from training
   only, with a separate later inner validation period to select method. Never
   calibrate on the outer/test sample or its class prevalence. Residual variance
   and distribution shape obey the same restriction.
6. Add-one/remove-one feature-group ablations refit on the same games and folds.
   Missingness and failed joins are explicit; unknown labels are not invented.
   Registry entries need experiment evidence to become retained. Choose windows,
   interactions and denominators within development, not after final results.
7. Future-mutation tests must change later results, injury revisions, actual
   lineup, lines and labels while earlier feature/prediction hashes stay identical.
   No network calls in tests; disable dotenv and use synthetic/local fixtures.

## Smallest next executable implementation: RF-001

Implement an offline, opponent-adjusted score baseline plus the minimal historical
harness. No PBP, player component, market-assisted inputs, simulator, dashboard or
live-workflow change. First deliver a synthetic smoke run, then an authorized
bounded development-only real-data run after kickoff/label coverage audit.

**Inputs.** Explicit paths to pinned local Parquet/CSV game observations and a
manifest; no automatic network or all-season loader. Required fields:
`game_id, season, week, game_type, kickoff_ts_utc, home_team, away_team, location,
home_score, away_score`, plus `revision_id, published_ts/first_seen_ts,
fetched_ts, source_hash, availability_evidence, evidence_ref` for strict mode. Keep scheduled
prediction rows separate from labels. Reject ambiguous IDs/duplicates, joins
that multiply games, bad times and years outside the allowed development set.
Use existing franchise aliases (OAK/LV, SD/LAC, STL/LA) with a versioned mapping;
do not parse the ID as an alternative kickoff source. Config names cohort,
season ranges, tuning settings, refit rule and seed. No secrets needed.

**Fit.** Two rows per eligible prior game. Regularized weighted least squares:
`E(points_for_i) = league_intercept + offense_i + defense_opponent + home_bonus*h`.
`h=1` only for the team playing at home, otherwise zero (including both neutral
rows). Minimize `sum(w_r * (y_r - mu_r)^2) / sum(w_r)
+ lambda * (sum(offense^2) + sum(defense^2))`. For a game at prior kickoff t,
each team row has `w_r = 2 ** (-(as_of - t).total_seconds() / (86400 * half_life_days))`,
or 1 for no decay. Ridge offense/defense coefficients toward zero; intercept/home
bonus are unpenalized. Library Ridge's sum-loss alpha must therefore equal
`lambda * sum(w_r)` if using that parameterization. Build entity columns from
eligible training identities only; no target/future roster encodings or centering
over future teams. The league fit drops team effects, uses w=1 and the same
unpenalized intercept/home bonus. If eligible training has no home rows, fix its
unidentifiable home bonus to zero. Use no future-season intercepts.
Unseen teams use zero effects. Means clipped at zero by a fixed documented rule.
For each forecast, refit deterministically using only eligible earlier games;
no outer target labels. Record actual fit cutoff and eligible game IDs.

**Distribution.** Preserve opposing-score dependence by resampling paired
home/away residual vectors from earlier chronological T−24h training predictions.
For each fixed grid setting, create those mean predictions only from data eligible
at that prior game's cutoff; an eventual outer-selected recipe may replay this
past history, never use later games to fit an earlier mean. A residual enters
the reservoir only when its score-label revision is eligible at the current
cutoff. Each fit and label revision needs separate provenance. Center each
model's residual bank by its own current training-only residual mean.

First allow a mean prediction after 100 eligible training games; allow a
distribution after 50 eligible chronological residual pairs. Uniformly resample
all eligible paired residuals from that model/setting, with no extra decay,
season mixing rules, calibration or tail-scale tuning. The league comparator
uses its own no-decay out-of-sample residual bank, never candidate residuals.
This avoids giving its uncertainty a calibration fitted to the challenger.
Candidate numerical-fit failure or insufficient candidate residuals uses the
league fallback only if the league has met its own 100/50 gates. If neither
can predict, record a miss (warm-up role where applicable); do not fabricate
league residuals from in-sample errors. Missing required schedule identity/time
is an exclusion; corrupt input or an unexpected exception fails the run visibly.

Generate 10,000 pairs with a stable per-game seed: first eight bytes of SHA-256
of UTF-8 `run_seed|game_id|as_of_utc|distribution-v1`, big-endian unsigned integer,
using NumPy PCG64. Use the same random index sequence for paired models where
reservoir game IDs coincide; order reservoirs by (kickoff_ts_utc, game_id),
with one admissible score revision per game. Serialize as_of_utc as UTC ISO8601
with six fractional digits and Z, and run_seed as a decimal integer. Otherwise
log the distinct reservoirs. Add each
model's centered paired residual draw to its fitted means, round as floor(x+0.5)
then clip below zero. Save the exact ordered reservoir and samples. Rerunning with
an independent seed and 20,000 draws is a Monte Carlo sensitivity check, not a
tuning trial. Flag probability differences exceeding three combined binomial
Monte Carlo standard errors plus 0.001, and margin/total CRPS differences above
0.1 points; report counts and maxima rather than searching seeds to remove flags.
Samples model
statistical integer final scores including overtime; they do not model football
scoring sequences or rule mechanics. Save the probability table/samples rather
than claiming mechanically feasible exact-score simulation. Compute explicit
win/away/tie and the compatible home-result share from that same distribution.
The RF-001 support is **all nonnegative integer pairs**, not the set of feasible
football game histories. Rounding may generate very unlikely scores or impossible
pairs such as 1–0. Do not simply ban every score of one: the 2023 rulebook's
Rule 11 allows a one-point safety on a try after a touchdown. A score of one
against an opponent below six is a useful infeasibility diagnostic under those
rules. Save `score_one_draws` and `one_below_six_opponent_draws`; the latter is
not a complete historical feasibility test. Keep this fixed approximation for
RF-001 rather than inventing a scoring-play filter or projecting to multiples
of three/seven after looking at results. Flooring/clipping can shift the draw
mean and create mass at zero; saved expected points are computed from the
integer draws, separately from clipped regression means. Small football margins
and tie probabilities may be distorted. A rule-aware support model is a later
registered experiment, not part of RF-001.
For REG games ties remain in the distribution; do not condition them away for
the primary home-result-share score. For postseason final-score forecasts, reject
tied draw pairs and sample until 10,000 non-tied pairs are retained (cap at
1,000,000 attempts, then fail/fallback visibly). This is explicit conditioning,
not an overtime simulator or a learned tie-break rule. Save rejection counts;
postseason p_tie must be zero. Use the observed final score including overtime
as the label, never use actual overtime occurrence as a pre-game predictor.
The [2023 official rulebook, Rule 16](https://operations.nfl.com/media/rwnj5upg/2023-rulebook_final.pdf)
documents regular-season ties and continued postseason play until a winner.
This audit did not verify every historical rule version; season-specific rule
metadata must be pinned before applying this postseason constraint to real runs.

**Outputs.** Under a new ignored `data/research/runs/<run_id>/`, never existing
`forecasts/`: immutable run/config/source manifest, split assignments and eligibility
exclusions, training audit/residual provenance, one saved prediction per
(game_id, model_version, cohort, as_of), joint-score samples/probability table,
fold/per-season/pooled metrics, paired differences/CIs and trial ledger.
Predictions include training cutoff, feature/input hash, seed, actual model/fallback,
expected team points from the saved draws (with fitted means separately labeled),
margin/total summaries and intervals, p_home/p_away/p_tie,
p_share, missingness and reconstruction flags. The forecast engine receives
schedule fields and eligible prior observations only, never the target score.
The separate evaluator releases each target's label only after its forecast
artifact is saved; it may then become a later training observation when eligible.
Do not pass a score-bearing target row to predict and merely promise to ignore
its score columns. Use manifest-listed season partitions with explicit roles and
reject unapproved/mixed-season artifacts before opening their data; post-read
season checks supplement this gate, they cannot undo holdout inspection.
Use a write-once run directory and fail on collision. Hash sorted inputs/config,
code SHA plus uncommitted patch hash, Python/uv.lock versions and artifact schemas.
Support development only by default, with a fail-closed final-holdout gate.

**Acceptance criteria.** In the same pinned runtime/numerical environment,
deterministic replay produces identical prediction and split hashes on permuted
input order; all used games/versions satisfy cohort gates;
no unrequested fetch or holdout artifact is opened. Frozen baseline golden outputs
and forecast CSVs unchanged. Home/away/tie sum to one; scores nonnegative integers;
margin/total/probabilities reconcile with saved joint samples. Each scheduled game
has a forecast/fallback/miss/exclusion record. Report RF-001 vs league and frozen
probability baselines on common games with all specified counts/metrics; improvement
is not a prerequisite for correct implementation. Full pytest and ruff pass.

**Meaningful tests first.** Write and observe failing synthetic tests before
production implementation: cutoff equality/four-hour boundary; delayed publication
and correction-version selection; future-label mutations; entire-game fold
isolation; inner-tuning/transform/residual isolation; neutral-site and unseen-team
behavior; hand-checkable opponent adjustment and weighted penalty scaling;
paired residual covariance and stable seed under row permutation; probability and
score-summary reconciliation including ties/OT; hand-calculated Brier/log-loss/CRPS;
paired block resampling; missing kickoff/duplicate game/alias joins; fallback/count
accounting; write-once outputs; default holdout rejection **before file access**.
Run with `PYTHON_DOTENV_DISABLED=1`; fixtures are synthetic/local, no network.
Exercise existing golden tests without editing their expectations. Documentation
does not need artificial unit tests.

## RF-001 implementation clarifications (2026-10-08, before real evaluation)

The offline entry point, schemas and artifacts are described in
[RF-001 implementation](rf001.md). This amendment resolves routine implementation
details using invented fixtures; it adds no historical accuracy evidence.

- Strict eligibility accepts declared `contemporaneous_receipt` or
  `timestamped_public_archive` evidence with a nonempty `evidence_ref` and a
  SHA-256 source hash. Receipts use the earlier recorded first-seen/receipt time,
  additionally requiring a supplied publication time to precede cutoff. An
  archive uses its audited publication time. A retrospective fetch, a date-only
  time, or an evidence type without a reference cannot establish eligibility.
  The offline runner checks these declarations; it cannot authenticate an
  external archive or prove a source's first publication. A real manifest must
  be reviewed with its referenced evidence before using the strict badge.
- Both cohorts require `completed=true` and both scores for training/residual
  labels. Reconstructed input is explicitly declared final retrospective data;
  its latest pinned revision is a hindsight assumption, not historical timing
  proof. The evaluator selects the latest pinned completed label separately.
  Reject duplicate revisions, equally timed label revisions and changes in
  canonical home/away identities. Missing schedule versions do not create a
  second exclusion for a game that has a usable version.
  Select the latest admissible revision before testing whether scores are
  completed/present: an available withdrawal removes an older score rather than
  silently restoring it. A latest reconstructed schedule with missing kickoff
  remains excluded rather than borrowing the earlier revision's time.
- Tune once at the first scheduled forecast cutoff of each outer season. At that
  cutoff, score saved candidate inner forecasts against the latest **then
  admissible** label versions. Compare the nine raw recipes on common inner
  games. Fallback predictions do not masquerade as candidate trials. If there
  are no common eligible inner forecasts, use the league fallback if its gates
  pass, otherwise record a miss; record the absence of a selected recipe. Do
  not choose a default setting based on outer outcomes.
- Replay all nine fixed settings chronologically to preserve their training-only
  residual histories. Fits before 2012 supply warm-up residuals; 2012–2014 are
  inner-only; 2015–2023 can enter later seasons' inner folds, but each outer
  season's selection uses strictly earlier seasons. Synthetic sparse fixtures
  do not establish that the planned real folds have adequate coverage.
- Save available mean fits even when residual gates have not passed. Each bank
  entry links its original fit artifact, T−24h cutoff and subsequent label
  revision. League residuals have their own saved mean fits. Unknown rest stays
  unknown; rest slices use eligible previous game kickoffs, never later labels.
- Main draws use the specified seed and PCG64 stream. The 20,000-draw sensitivity
  uses a separate `mc-sensitivity-v1` seed namespace, without selecting seeds.
  For result share, Monte Carlo variance is `p_home + .25*p_tie - p_share**2`
  because a draw can contribute 0, .5 or 1. For home/away/tie use binomial
  variance. This corrects the earlier generic binomial description for share.
  Energy pairs use `energy-v1`; the repeat uses that integer seed plus one;
  discrete PIT uses plus two. All seeds are saved. Samples and ordered banks
  suffice to reproduce sensitivity draws from the saved recipe/seed.
- Weeks shorter than a four-week block use that season's entire available week
  count as the block length. Such sparse synthetic/limited cohorts can have
  degenerate four-week intervals; report week counts and one-week/season
  sensitivities. Do not treat a degenerate interval as strong evidence.
- Reports are descriptive; no automatic promotion or historical accuracy claim.
  Metrics are conditional on saved forecasts with finalized labels. Coverage,
  unknown labels and full eligible Brier bounds accompany them. Frozen scalar
  models do not receive invented score or three-way distributions. Market-mid
  is explicitly unavailable when no aligned quotes were provided.
- A manifest declares single-season local CSV/Parquet partitions, their roles
  and hashes. Validate every declaration before opening any game artifact;
  reject 2024/2025, mixed-season declarations, symlinks and unsafe paths. A hash
  does not prove season isolation: audited metadata is the pre-read trust
  boundary, with post-read season checks as a supplement. There is no holdout
  override or download path. Real runs also require reviewed kickoff/label
  coverage and pinned season-specific postseason rule metadata.
- Run directories are write-once; a failed run leaves a failure record and is
  never silently resumed or overwritten. Predictions are flushed before
  evaluator release. Reproducibility is conditional on the pinned numerical
  environment; source files, Git SHA, tracked dirty patch, Python, NumPy and
  `uv.lock` hashes are recorded, including new untracked code by content hash.

No eligible real input manifest exists in this workspace as of this implementation
review. The earlier source samples are field evidence, not a complete historical
dataset or strict publication archive. Next is an explicitly authorized,
development-only input preparation and completeness/evidence audit, followed by
a bounded reconstructed evaluation. Strict historical evaluation remains gated
on authentic archived schedule/result revisions and publication evidence.

## RF-001 review amendment: penalty scale (2026-10-08)

Before any real evaluation, replace the original mean-loss penalty grid
`{1, 10, 100}` with `{0.0003, 0.001, 0.003}`. The original implementation
correctly minimized the specified objective; the original **scale** was unsuitable
for testing informative opponent adjustment. A balanced invented 32-team,
496-game league with known, distinct offense/defense effects recovered only
about 3% of the effects at lambda=1. This is synthetic recovery evidence, not
historical performance evidence.

For centered effects in a balanced T-team design, an effect column's average
information is approximately p=1/T. A scalar contrast has ridge attenuation
`p/(p+lambda)`; off/def cross-terms perturb that approximation. For T=32, the old
penalties dwarf p=0.03125. The amended grid penalizes at approximately 1%, 3% and
10% of that information scale, targeting substantial retention of identifiable
effects (roughly 99%, 97% and 91% in the scalar approximation). These weak-to-moderate
levels are prior design assumptions checked against invented known effects,
not selected by NFL outcomes or sportsbook/market comparisons. There is no
synthetic search for the best predictive score. A recovery test requires the
least-penalized setting to recover at least 75% of both generating effects, and
a separate three-team, hand-calculated matchup test distinguishes opponent
defense from own defense. Direct `fit_score` calls default to central lambda=0.001.

The mean-weighted objective, nine-setting budget, recency grid, chronological
selection and tie-breaker remain unchanged. Penalty scaling does not disappear
with more data under this mean-loss parameterization. A learned prior/variance,
sample-size-dependent penalty, new distribution support, exact atom evaluation,
residual windows and altered warm-up/holdout seasons remain separate experiments.
The original synthetic example is retained as a v1/old-grid example and must not
be presented as the amended recipe's output.

## RF-001 review amendment: input and artifact integrity (2026-10-08)

Core schema headers and exact completion encodings fail visibly when malformed.
An explicitly recorded dataset-wide clock orders revisions: publication time
for strict PIT by default, fetch time for reconstruction by default, or a
manifest-declared publication/receipt/fetch clock. Multiple versions require
distinct nonmissing times on that clock; no revision-ID text tie-breaker or
per-row clock fallback is allowed. Duplicate physical games under different IDs
and overlapping latest team schedules are rejected, while same-ID revisions
remain permitted. Synthetic partitions require `synthetic://` evidence markers;
markers and season-isolation declarations remain audited trust boundaries.
Parse the exact bytes that were hashed. Real runs and CLI diagnostics use the
registered seed 20261008; alternative API seeds are permitted only for marked
synthetic diagnostics. No seed searching is allowed.

Artifact schema v2 replaces embedded full training/residual histories with
shared immutable content-addressed records and ordered prefix sequences. Each
fit retains coefficients, settings, cutoff, input hash and training-root reference.
Each residual retains original mean, original fit and target-schedule references,
and the currently admissible label reference. Forecasts retain their own target,
cutoff, seed, summary and sample hashes; identical arrays/tables are stored once.
Readers verify reference hashes and reconstruct ordered inputs/banks without
source downloads. Earlier v1 runs remain immutable and are not schema-v2 evidence.
Alias version, relevant transitive baseline sources and numerical/dependency
build metadata accompany the working-code/lock hashes. Initialization failures
and interrupts after output creation leave failure records when storage permits.

Exclusions retain known type/week/location metadata. Eligible, predicted, missed,
fallback, excluded, unlabelled and scored counts are distinct. PIT reports include
ten fixed equal-width bins on [0,1] with the right endpoint in the last bin.
Identical fallback and league distribution inputs receive one sensitivity check
listing both models; diagnostic counters count computations, not aliases.
The comparison population still includes registered fallbacks. Candidate-only
comparisons, exact atom scoring, different residual windows, different tie/OT
mechanics, date-only training, cancellation/relocation policies and any warm-up
or locked-holdout changes require separate explicit amendments. No such redesign
is made here, and no real outcomes have informed these amendments.

## RF-001 first reconstructed execution policy (2026-10-08)

Policy ID: `rf001-reconstructed-2006-2023-v1`. This resolves preparation gates
before any real fitting or tuning. It uses source coverage and authoritative
rules, not historical predictive performance. The first execution input contains
exactly one schedule and one label partition for each starting-year season
**2006–2023**, with no `baseline_warmup` partitions. Both frozen probability
baselines replay only eligible observations from 2006 onward, using their existing
initialization and season transitions unchanged. The candidate and league score
models also start in 2006. Years 2006–2011 remain model/residual warm-up, 2012–2014
inner-only, and 2015–2023 outer evaluation. The nine-setting grid, nested tuning,
100/50 gates, finish lag, seeds, metrics, residual window, MC sampling, tie handling
and locked 2024–2025 contract are unchanged.

The earlier preparation archive `nfldata-93a5221-development-v2` includes optional
1999–2005 baseline history because the original foundation allowed it. That was
extra preparation beyond the requested 2006–2023 development range. Its 259
missing-time exclusions are all in 1999; they are not development exclusions.
No times are imputed or parsed from game IDs. Preserve that archive and its audit,
but do not feed its optional partitions into this first run. Source-audit rows
and raw archival fields are not model inputs. The original optional history is
superseded for this execution by the explicit 2006-only baseline start. This is
an input-history decision, not a change to frozen Elo/home-rate mathematics or
golden expectations. A future alternative warm-up comparison requires a separate
registered recipe; do not select a start year after looking at scores.

The first reconstructed statistical population is **completed, nonvoid games**.
The NFL canceled 2022 Week 17 BUF at CIN and did not assign a final result. The
immutable source omits that row. Exclude `2022_17_BUF_CIN` from score training,
residual construction, tuning and metric denominators. Retain an externally
documented exclusion with ID, starting-year season, week, REG type, designated
sides, cancellation reason and official citation. Do not invent a kickoff,
location, `as_of`, prediction or label. This retrospective population definition
does not claim the cancellation was known at historical T−24h. A prospective
forecast for an eventually canceled game would still be retained and marked
void/unscored after the fact; it must not disappear from prospective logs.

Separate population accounting must show **4,862 documented scheduled games =
4,861 completed input games + one externally excluded no-contest** for 2006–2023.
For 2022 alone: 272 REG scheduled, 271 REG completed, 13 postseason completed;
285 documented scheduled in total and 284 input games. All existing attempted,
eligible, predicted, missed, fallback, excluded and scored metric counters refer
to the actual input population; coverage is conditional on this completed-game
reconstruction. External cancellation accounting is a separate top-level report
and artifact, not a fabricated missing-input prediction. Existing slices, paired
comparisons and promotion gates are unchanged. Missing ordinary inputs and failed
predictions within the defined population remain visible and cannot be relabeled
as no-contests. Source omissions other than this audited exception fail the
completeness gate. If the canceled ID appears in any supplied schedule or label
revision, refuse this omitted-row recipe rather than silently discard it.

Before reading game partitions, a real execution requires an explicit versioned
`execution_policy`, exactly the approved season/kind declarations, and reviewed
season-specific postseason evidence. After loading, reconcile schedule/completed
label identities and per-season counts with the policy; no fit is needed for
this preflight. Save the policy in run provenance, persist external exclusions,
and include both populations in the metric report. Human audit assertions remain
a trust boundary. Do not use the earlier advisory `runner_ready` flag as proof.

The [postseason rules audit](nfl_postseason_rules.md) distinguishes annual books,
dated official rules explanations and any historical continuity inference. Each
included season needs its own reviewed evidence entry. Only the no-final-tie
support is used: the model neither learns nor simulates historical OT mechanics.
Final-score residuals may span different OT eras under the already registered
pooled-bank approximation. This is reconstructed evaluation only; final schedule
and score revisions do not establish historical publication or flex timing.
Data-specific redistribution rights remain unresolved and the artifacts stay
local and ignored. These limitations do not open or weaken the holdout lock.

## RF-001 historical moneyline reference amendment (2026-10-08 America/Los_Angeles)

**Status: approved definitions; committed before outer RF-001 results may be
viewed. This does not authorize the historical backtest.** This narrowly scoped
historical reference changes no RF-001 training input, feature, recipe, tuning,
fold, comparison population, or registered metric. It does not amend
`RESEARCH_PROTOCOL.md`; its prospective-only rule for the live test remains
unchanged. Odds are evaluator-only and never training inputs, RF-001 features,
or a substitute for a same-cutoff T−24h comparison. The required label is
**“historical moneyline reference; timing and book unknown.”** Timing, bookmaker
or aggregation, and settlement semantics are unknown limitations, not blockers
for this exploratory reference. No market-superiority or strict historical
point-in-time claim is admissible.

**Source extraction and de-vig.** A future odds extractor must select rows by
explicit season key, independent of source-file ordering, and write content-
hashed season partitions with source and extraction provenance. The first
development use is limited to 2006–2023; the extractor must not read 2024–2025
outcome rows. For finite integer American odds `a` with `abs(a) >= 100`, derive
raw implied probability `q = 100/(a+100)` for positive `a`, and
`q = (-a)/((-a)+100)` for negative `a`; zero, missing, noninteger, or otherwise
invalid values are unsupported. Primary proportional de-vig is
`p_i = q_i / (q_home + q_away)`. The fixed secondary power sensitivity solves
the unique `k > 0` for which `q_home**k + q_away**k = 1`, and reports
`p_i = q_i**k`. It is unsupported for an invalid/missing pair, raw probabilities
outside `(0,1)`, or failed root bracketing/convergence; no fallback value is
substituted. No calibration or book weighting is fit.

**Population and scoring.** The primary odds population is decisive completed
outer games (2015–2023) with valid paired moneylines (`y=1` home win, `y=0` away
win). Interpreting normalized two-way odds as a conditional decisive-game win
probability is an explicit research assumption; excluding ties does not establish
refund-on-tie settlement. Use the exact label **“historical moneyline reference;
timing and book unknown.”** For RF-001 candidate and registered fallback rows,
use the saved `p_cond = p_home / (p_home + p_away)`; a zero or nonfinite
denominator is unsupported. Do not substitute `p_share` or `0.5`. Elo and
home-rate supply scalar probabilities without separately identified tie probabilities; score
those saved values unadjusted on the decisive subset and disclose that this is an
approximation to a conditional probability. Do not invent tie probabilities or
alter RF-001 to match the scalar forecasts. Constant `0.5` is exact under both
interpretations. Use binary Brier and binary log loss with the 0/1 target on
identical rows for each registered pair; keep
these decisive-game results separate from all-game fractional-label metrics.
The source has only home/away moneyline fields, so no three-way market branch is
defined. Margin CRPS remains unsupported for the moneyline and scalar forecasts.

The existing RF-001 Monte Carlo probability checks cover `p_home`, `p_away`,
`p_tie`, and `p_share`, not the conditional ratio `p_cond`. Before filling
conditional-probability cells, a future evaluator must add and pass a meaningful
synthetic test and report a fixed-seed `p_cond` Monte Carlo convergence/error
sensitivity using the registered draw recipe and independent sensitivity seed;
do not search seeds or tune this diagnostic.

**Comparisons, gates, and reporting.** Preserve all registered RF-001 pairwise
comparison populations and inclusion of predeclared fallback predictions as
primary. All-model complete-case tables and candidate-versus-fallback splits
are descriptive. Keep football-backtest execution gates independent from this
reference: unknown timing, book/aggregation, and settlement semantics are
disclosed limitations, not blockers for the registered football-only run or this
exploratory reference. The
evaluator may be implemented later only if it follows these approved, committed
definitions unchanged, passes meaningful synthetic tests, and is itself
committed before closing-reference scores are computed. Any deviation requires
a separate registered experiment and must not silently amend these definitions.
The selection rules are fixed in advance; after a separately authorized
evaluation, report realized valid-pair,
decisive-game, tie-exclusion, paired-prediction and missingness counts. Those
realized counts are descriptive reporting, not pre-run gates or grounds to
change the registered population. Apply the existing paired week-block bootstrap
and seed to admissible paired rows. Publish results regardless of direction.

The amendment does not authorize a historical run or relax the locked 2024–2025
holdout.
