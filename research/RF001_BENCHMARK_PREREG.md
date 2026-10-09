# RF-001 benchmark pre-registration

**Status:** Approved definitions, to be frozen by commit before outer RF-001
results are viewed. This file does not amend the live protocol or authorize a
historical backtest. No benchmark scores, model predictions, or historical
evaluation results have been viewed.

**Proposed experiment:** report the registered RF-001 outer-development
comparisons under their existing pairwise populations and registered fallbacks.
A separate historical moneyline reference may be shown under the definitions
below. This is development evidence, not a final holdout or a claim of market
superiority.

## Contract conflict and required resolution

The historical reference is governed by the dated amendment in
`research/evaluation_protocol.md` (2026-10-08 America/Los_Angeles). These
definitions must be committed before anyone views outer RF-001 results. The
reference is evaluator-only later information, never a training input, RF-001
feature, T−24h comparison, or live benchmark. The amendment leaves
`RESEARCH_PROTOCOL.md`'s prospective-only rule for the live test unchanged.
The label is exactly **“historical moneyline reference; timing and book
unknown.”** The source does not establish closing status, bookmaker or
aggregation, quote timestamp, or tie settlement. These are disclosed
limitations, not blockers for this exploratory reference. Interpreting the
normalized two-way odds as a conditional decisive-game win probability is an
explicit research assumption. Excluding tied outcomes from this comparison does
not establish that a contract refunds ties.

The existing protocol requires book identity, both sides, line/OT/tie/push
rules, snapshot and quote-update times for a same-time sportsbook comparison.
The pinned file has paired side fields but no bookmaker or quote timestamp, so
it cannot establish a same-time price or qualify for a matched T−24h claim. These
unknowns are disclosed limitations for this exploratory historical reference,
not score-fill blockers.

## Data and label definition

Pinned source: `nflverse/nfldata` commit
`93a5221070bcd1733fe3c55abb48e931b3615241`, `data/games.csv`, SHA-256
`fb2a5a96e2bd0ddc1b6ddbd487c89857b216114e5ce296214e5b54b6d75bbc43`.
The relevant columns are `home_moneyline`, `away_moneyline`, `spread_line`,
`home_spread_odds`, and `away_spread_odds`. The audit stopped at the first
season after 2023; no 2024–2025 outcome fields were inspected.

The CSV identifies odds/lines but contains no field named `closing`, bookmaker
identity, quote-update timestamp, or price-snapshot timestamp. Project inventory
calls them “closing lines,” but the source dictionary does not establish that
semantics. Report the reference only with the exact label above and the caveat
that timing, book, and aggregation are unknown. It is neither a verified closing
price, a same-cutoff/T−24h benchmark, nor a known sportsbook consensus.

### Odds conversion

For valid American moneyline `a`, calculate its raw implied probability
`q = 100 / (a + 100)` when `a > 0`, and
`q = (-a) / ((-a) + 100)` when `a < 0`. Zero is invalid. For each game with
valid paired home and away odds, proportional de-vig is

`p_home = q_home / (q_home + q_away)` and
`p_away = q_away / (q_home + q_away)`.

Proportional de-vig is primary. The fixed secondary power-method sensitivity
uses the same raw probabilities and solves for the unique `k > 0` satisfying
`q_home**k + q_away**k = 1`; report `p_home = q_home**k` and
`p_away = q_away**k` (these sum to one by definition). Solve deterministically
by bisection: start with lower bound 0 and upper bound 1; double the upper bound
until the equation's left side is at most 1, then bisect for at most 100
iterations or until the interval width is at most `1e-12`. If the odds pair is
missing, invalid, nonfinite, yields a raw probability outside `(0,1)`, or the
root cannot be bracketed/converged, mark this sensitivity unsupported; do not
substitute proportional de-vig for a missing sensitivity value. Do not fit a
calibration model or tune a bookmaker weight. Do not infer a probability from
`spread_line` or its prices.

For the coverage audit, a valid American-odds value is a finite integer with
absolute value at least 100; a valid pair requires both sides. A valid spread
line is finite numeric `spread_line`; a valid spread-price pair requires both
spread-odds columns to satisfy the American-odds rule. Empty fields are missing,
not invalid. Report nonempty invalid fields separately. This convention is
fixed before any benchmark score is viewed.

## Pinned-source coverage audit

A schema-only/coverage audit of the pinned CSV (not a model evaluation) streamed
through seasons 2006–2023 and stopped on the first later-season boundary. It
verified the raw SHA-256 above. “ML pair” means both moneyline values are present
and valid; “spread pair” means both side spread prices are present and valid.
`spread_line` is counted separately. Missing fields and nonempty invalid numeric
values are reported separately; the validity rules are those above.

| Season | Games | Valid ML pairs | ML missing pairs | Invalid ML fields | Valid spread lines | Valid spread-price pairs | Spread-price missing pairs | Invalid spread-price fields |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2006 | 267 | 220 | 47 | 0 | 267 | 220 | 47 | 0 |
| 2007 | 267 | 266 | 1 | 0 | 267 | 266 | 1 | 0 |
| 2008 | 267 | 194 | 73 | 0 | 267 | 194 | 73 | 0 |
| 2009 | 267 | 253 | 14 | 0 | 267 | 253 | 14 | 0 |
| 2010 | 267 | 267 | 0 | 0 | 267 | 267 | 0 | 0 |
| 2011 | 267 | 267 | 0 | 0 | 267 | 267 | 0 | 0 |
| 2012 | 267 | 267 | 0 | 0 | 267 | 267 | 0 | 0 |
| 2013 | 267 | 267 | 0 | 0 | 267 | 267 | 0 | 0 |
| 2014 | 267 | 267 | 0 | 0 | 267 | 267 | 0 | 0 |
| 2015 | 267 | 267 | 0 | 0 | 267 | 267 | 0 | 0 |
| 2016 | 267 | 267 | 0 | 0 | 267 | 267 | 0 | 0 |
| 2017 | 267 | 266 | 1 | 0 | 267 | 266 | 1 | 0 |
| 2018 | 267 | 267 | 0 | 0 | 267 | 267 | 0 | 0 |
| 2019 | 267 | 267 | 0 | 0 | 267 | 267 | 0 | 0 |
| 2020 | 269 | 269 | 0 | 0 | 269 | 269 | 0 | 0 |
| 2021 | 285 | 285 | 0 | 0 | 285 | 285 | 0 | 0 |
| 2022 | 284 | 284 | 0 | 0 | 284 | 284 | 0 | 0 |
| 2023 | 285 | 285 | 0 | 0 | 285 | 285 | 0 | 0 |
| **2006–2023** | **4,861** | **4,725** | **136** | **0** | **4,861** | **4,725** | **136** | **0** |
| **Outer 2015–2023** | **2,458** | **2,457** | **1** | **0** | **2,458** | **2,457** | **1** | **0** |

Both moneyline sides were missing together in all 136 missing-pair rows; no
partial or nonempty invalid moneyline values were found. The same counts hold
for paired spread prices. `spread_line` was finite numeric in all 4,861 rows,
with no missing or invalid values. This establishes field completeness only, not
that values are closing, same-book, or time-stamped. On the outer denominator,
paired moneyline coverage is 99.96%; the one missing pair remains visible in
all subsequent coverage and exclusion reports.

## Existing eligible comparisons

| Forecast/comparator | Probability or distribution available | Primary status |
|---|---|---|
| Constant `0.5` | Binary home-result-share probability | Eligible fixed baseline |
| `home-rate-v0` | Frozen scalar probability | Eligible; replay without recalibration |
| `elo-538-default-v0` | Frozen scalar probability | Eligible; replay without recalibration |
| RF-001 candidate | Saved `p_share` and joint integer score distribution; saved `p_home`, `p_away`, and `p_tie` | Eligible; retain candidate status explicitly |
| RF-001 registered league fallback | Its saved `p_share`, score distribution, and component probabilities | Eligible as the registered RF-001 output; label every row `fallback`, never merge it into candidate-only counts |
| `market-mid-v0` | Requires a saved, aligned prediction-market quote | Unavailable from this pinned games CSV; include only if an already archived same-cutoff quote meets the fixed protocol, otherwise mark unsupported/missing |
| Historical moneyline reference; timing and book unknown | Paired implied probabilities from the pinned odds fields under the explicit conditional-win-probability assumption | Exploratory reference only; not a verified close, T−24h comparator, or known consensus |
| Spread fields | Point line and side prices | Coverage audit only here; do not manufacture score or margin distributions from them |

The primary football-backtest comparisons retain the registered population for
each pairwise comparison and the registered RF-001 candidate/fallback behavior.
Do not redefine these populations as an all-model complete case. Candidate and
fallback labels, counts, losses, and coverage remain visible; the registered
pipeline comparison includes its predeclared fallbacks. An all-model
complete-case table and candidate-versus-fallback split are descriptive only.
For every pair report the full eligible outer denominator, paired count, misses
and exclusions with reasons, and each model's prediction coverage. Preserve the
registered block bootstrap and sensitivity populations.

The primary odds population is decisive completed outer games (2015–2023) with
valid paired moneylines. The outer denominator is 2,458 completed, nonvoid
games for 2015–2023. The pinned odds audit found 2,457 valid paired moneylines and one game with both
moneyline fields missing; no nonempty invalid moneyline values were found under
the rule above. Report realized valid-pair, decisive-game,
tie-exclusion, and paired-prediction counts after the run, alongside all missing
and invalid odds and forecast exclusions. These counts are reporting results,
not reasons to change the selection rule. This is not the all-game win-share
population. The pinned source has only two moneyline
columns (`home_moneyline`, `away_moneyline`); it does not support a three-way
market branch.

## Outcomes and scoring

The fixed `RESEARCH_PROTOCOL.md` defines the binary home-result-share target as
`y = 1` for a home win, `y = 0` for an away win, and `y = 0.5` for a tie. Follow
that definition for Brier and fractional-label **binary win-share log loss**
for all-game football-model comparisons. RF-001 maps its joint distribution to
`p_share = P(home win) + 0.5 * P(tie)`. Scalar baselines retain their saved
probability semantics. Binary log loss is
`-[y log(p) + (1-y) log(1-p)]`; do not substitute categorical loss.

On the primary odds population—decisive completed outer games (2015–2023) with
valid paired moneylines—score the normalized two-way implied probability under
the explicit research assumption that it represents a conditional decisive-game
win probability (`y=1` home win, `y=0` away win). Label it “historical moneyline
reference; timing and book unknown.” Excluding tied games does not establish tie
settlement. For each
RF-001 candidate or fallback forecast use
`p_cond = p_home / (p_home + p_away)` from its saved distribution. If the
denominator is zero or nonfinite, that model's row is unsupported; never
substitute `0.5` or its all-game `p_share`. Its registered Monte Carlo checks
cover `p_home`, `p_away`, `p_tie`, and `p_share`, but not `p_cond`; disclose this
gap and report a fixed-seed conditional-ratio convergence/error sensitivity
before interpreting any such cells. This sensitivity must use the already
registered draws/independent sensitivity seed, not seed search or tuning.

Elo and home-rate are scalar forecasts and do not provide a separately
identified tie probability. Score each saved scalar unchanged on this decisive
subset and label it an approximation to the conditional decisive-game
probability; do not infer or invent a tie probability and do not alter the RF-001
conditional mapping to match it. Constant `0.5` is exact under either
interpretation. Compare all forecasts on identical rows per registered pair.
Use binary Brier and binary log loss with the 0/1 target on this decisive subset.
Do not compare its scores or intervals as if they were the all-game
fractional-label metrics above. Unknown settlement semantics remain an explicit
limitation, not a blocker for this exploratory reference.

Three-outcome home/tie/away football scoring is a different target and a
different loss: use the observed class and a complete `(p_home, p_tie, p_away)`
forecast for multiclass Brier and categorical log loss when registered. RF-001
can supply such a distribution when available. Do not invent three-way
probabilities for Elo or another scalar model; unsupported comparisons stay
blank. This is a football-outcome metric only; do not infer a three-way market
from the pinned two-column moneyline source. Do not compare categorical log loss
to binary fractional-label log loss as if they were the same metric.

Apply the existing numerical policy unchanged: Brier is unclipped; binary and
categorical log loss clip probabilities only at `[1e-6, 1 - 1e-6]` and report
clipping counts and unclipped extremes. Keep finite extreme odds probabilities;
exclude a quote only for missing/invalid sides, nonfinite conversion, or an
impossible zero denominator. Do not winsorize, cap, or choose exclusions after
viewing losses. For binary forecasts exactly at 0 or 1, preserve the predeclared
clip and count.

Margin CRPS is reported only for a model's justified full predictive
score/margin distribution. RF-001 candidate and league fallback may receive
margin CRPS when the required saved draws exist. `0.5`, home-rate, frozen Elo,
`market-mid-v0`, and the historical moneyline reference receive blank/unsupported margin-CRPS
cells. A spread line or moneyline probability does not identify a full score
distribution. Other score-distribution metrics follow the evaluation protocol;
unsupported cells remain blank with reason codes.

## Chronology, uncertainty and reporting rules

Use the fixed `rf001-reconstructed-2006-2023-v1` cohort and its rules: 2006–2011
warm-up, 2012–2014 inner-only, outer seasons 2015–2023, and no 2024–2025 input.
Keep frozen baselines' 2006 replay start and calculations unchanged. Do not
retune, recalibrate, change residual windows, or select variants on outer results.
The historical moneyline reference is evaluator-only, with timing and book
unknown; it never enters training or RF-001 features. Preserve the actual
RF-001 candidate/fallback label on every forecast.

For each comparator, calculate per-game candidate-minus-baseline losses on
common rows and report pooled and per-season means, sample sizes and Brier skill
denominators. Use the registered **5,000 paired block-bootstrap replicates, seed
20261008**, with games grouped into chronological football weeks within season,
REG weeks followed by postseason rounds in kickoff order, noncircular contiguous
four-week blocks, and the registered one-week and whole-season sensitivities.
Publish the registered percentile 95% intervals. These intervals condition on
saved predictions and do not include model refitting or tuning uncertainty. For
the historical-moneyline-reference subset use the same block/seed rules on its paired rows;
show that subset's coverage and denominators. Do not invent an odds-specific
uncertainty method.

Publish results regardless of direction. Show all eligible outer games,
per-model coverage, misses/exclusions/unlabelled rows, every registered pairwise
population, and candidate-versus-fallback counts. An all-model complete-case
table is descriptive. Report the separate odds-complete/decisive subset only
where admissible, and do not silently drop failures or describe a paired mean as
an all-game result. Record missing odds and source-semantic gaps.
Make no post-viewing metric, clipping, tie, subset, or benchmark changes. A
negative paired score is not evidence of superiority by itself. No market-
superiority or strict historical point-in-time claim is admissible from this
historical moneyline reference. Market superiority requires an appropriate
same-cutoff comparison with verified timestamp, book, contract mapping and
settlement rules.

## Separate execution and reference reporting

The football backtest follows the independent gates and recipe in
`research/evaluation_protocol.md`; no odds source or score is a gate for
that run. Unknown timing, book/aggregation, and settlement semantics are
limitations to report, not blockers for the exploratory reference. The evaluator
must follow these approved, committed definitions unchanged, pass meaningful
synthetic tests, and be committed before any historical moneyline reference scores are
computed. Any deviation must be documented as a separate experiment and cannot
silently replace these definitions. After an authorized run, report actual
coverage counts, exclusions, and tie counts without changing eligibility.

Any future odds extractor must filter by an explicit season key, independent of
CSV/file ordering, and write content-hashed per-season partitions with provenance.
For the first development run it must admit only 2006–2023 seasons and must not
read 2024–2025 outcome rows. The existing audit table is a source audit, not a
model-input manifest. No historical run is authorized by these definitions.
