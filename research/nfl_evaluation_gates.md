# RF-001 evaluation gates and first-run proposal

2026-10-08. This resolves input and population decisions before any historical
fit. No historical fit, tuning, backtest or holdout evaluation was executed.
The dated decision is in [the evaluation protocol](evaluation_protocol.md).
The [postseason rules audit](nfl_postseason_rules.md) is separate from the
[preparation audit](nfl_data_preparation.md); rule sources do not become features.

## Why 1999 appeared and exactly what the manifests contain

The original protocol permitted optional 1999–2005 initialization history for
the frozen probability baselines. I prepared that optional history along with
development rather than keeping the first input limited to the requested
2006–2023. That added preparation scope without performing a historical run.
The earlier `nfldata-93a5221-development-v2/manifest.json` contains **50 declared
model-table partitions**: one schedule and one label CSV for every year
1999–2023. Years 1999–2005 have role `baseline_warmup`; 2006–2023 have role
`development`. The older partitions are not merely raw-source audit records:
under the earlier runner they could initialize frozen baselines, although the
score model filters history to 2006 onward. All 259 missing-time exclusions are
1999 games, so they do not indicate missing 2006–2023 development kickoffs.

The original archive remains unchanged. The first-execution build is
`data/research/inputs/nfldata-93a5221-rf001-2006-2023-v1/`.
Its `execution-manifest.json` declares **36 model-table partitions**: separate
schedule and label CSVs for exactly 2006, 2007, 2008, 2009, 2010, 2011, 2012,
2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022 and 2023.
Every partition has role `development`. There is no 1999–2005 model input and no
2024–2025 partition. January/February postseason dates remain assigned to the
starting-year season: a February 2024 game in the 2023 postseason is not a
2024-season holdout game.

The pinned multi-year raw CSV is a source archive, never an input partition.
`source-rows-Y.json` preserves source columns for audit and is not loaded by
RF-001. Only the explicitly declared schedule and label CSVs are read as model
inputs. QB, coaching, sportsbook odds, rest and weather columns in audit rows
remain outside this score model. No later-season outcome fields were inspected.

## Warm-up and cancellation decisions

The first recipe uses eligible history starting in **2006 for every model**.
Frozen Elo initializes from its existing defaults and retains its existing
season transitions; home-rate uses its existing formula and missing-history
behavior. No frozen function or golden expectation changes. Years 2006–2011
warm up the new fit and chronological residual bank; 2012–2014 are inner-only;
headline outer evaluation remains 2015–2023. Early warm-up insufficiency stays
visible. No historical performance was used to choose the start year.

The NFL's [official club cancellation announcement](https://www.buffalobills.com/news/nfl-says-neutral-site-afc-championship-game-is-possible-bills-bengals-week-17-ga)
documents that 2022 Week 17 BUF at CIN would not resume, with both teams' seasons
containing 16 completed regular games. This source omits the canceled game.
The first reconstructed statistical cohort contains completed, nonvoid games.
Exclude `2022_17_BUF_CIN` from all training, residuals, tuning and scoring;
persist its ID/season/week/type/sides/reason/citation in a separate external
population ledger. Do not synthesize a kickoff, location, cutoff, forecast or
score label. The external record is not a missing-input prediction.

For 2006–2023, **4,862 documented scheduled = 4,861 retained completed + one
external no-contest**. In 2022, **285 = 284 + one** (272 REG scheduled, 271 REG
completed and 13 postseason completed). Existing metric attempted/eligible,
miss/exclusion, fallback, slice and promotion counters keep their definitions
and cover actual RF input games. A new top-level population report shows the
external exclusion and per-year accounting separately. Coverage is conditional
on completed, nonvoid games, not coverage of every originally scheduled event.
The headline outer years 2015–2023 contain **2,459 documented scheduled = 2,458
retained completed + one no-contest**; the 4,861-input total also includes warm-up
and inner-only years and is not the outer metric denominator.

This selection uses finalized cancellation status retrospectively. It does not
assert that the no-contest was known at T−24h or authorize a future-information
feature. Prospective forecasts made before an eventual cancellation must remain
logged and subsequently marked void/unscored. Missing ordinary games cannot be
silently assigned the no-contest exception. An external canceled ID overlapping
any supplied schedule or label revision fails this omitted-row recipe.

## Evidence, enforcement and provenance

The structured postseason evidence assigns an entry to every input season,
distinguishing annual books from official dated explanations and amendment-chain
inferences. RF-001 uses only their no-final-tie support. It still rounds/clips
scores, permits REG ties and rejects POST tied draws under the registered
residual approximation. It does not simulate historical possessions or overtime
mechanics. Pooling prior final-score residuals across different OT eras remains
the existing model limitation; no statistical redesign was added.

`load_manifest(..., require_execution_policy=True)` checks the versioned real
execution policy, exact season/kind declarations and reviewed postseason entries
before reading game files. Normal RF-001 execution always requests that gate.
Read-only loading of older preparation archives remains available without
calling a model. Post-read validation reconciles all identities, completed labels,
per-year counts and external exclusions without fitting. The older advisory
`runner_ready` flag does not authorize execution; an explicit valid policy does.

The execution manifest pins source, table, rule-evidence registry and dated
protocol hashes. The future run stores the complete source manifest and policy
hash, hashes and saves `external_population_exclusions.json`, and adds population
accounting to `metrics.json`. URLs/review flags are human-audited assertions:
offline validation does not authenticate the NFL website or cryptographically
prove when a source was published. All artifacts remain local and ignored.

24 new synthetic gate cases were first exercised as failures where behavior
was missing, then passed. They cover pre-read refusal, scope and rules, real
scheduled/completed counts, actual identity/label reconciliation, cancellation
overlap and separate output bookkeeping. A two-game invented run verifies the
external ledger without reaching a fit gate. Existing frozen logic and all
statistical calculations remain unchanged. Tests make no network calls and
disable dotenv.

## Exact proposed first backtest and resource estimate

**Proposal only; do not execute until separately authorized.** From the repository
root, with the existing environment and local input build:

```sh
PYTHON_DOTENV_DISABLED=1 UV_OFFLINE=1 UV_CACHE_DIR=/tmp/forecast-foundation-uv-cache \
uv run python -m lab.backtest.nfl_score \
  --manifest data/research/inputs/nfldata-93a5221-rf001-2006-2023-v1/execution-manifest.json \
  --run-id rf001-reconstructed-2006-2023-first-v1 \
  --seed 20261008
```

The run creates the new ignored
`data/research/runs/rf001-reconstructed-2006-2023-first-v1/` directory and refuses
an existing ID. It uses the registered nine settings, all chronological warm-up
and inner folds, outer 2015–2023, 10,000 primary draws, 20,000 sensitivity draws
and 5,000 bootstrap replicates. There is no holdout override or download option.

No full-history capacity measurement exists. Existing synthetic measurements
were 5.90 seconds for 192 games on the current grid and 68.48 seconds for 544
games on the older engineering grid. Simple quadratic extrapolations to 4,861
games give about **1.05–1.52 hours**; these are rough estimates that omit real
nested-selection/bootstrap costs and differences in chronology, sharing and
numeric libraries. They are not bounds or a promise of runtime.

For planning, reserve **4–8 hours**, **8 GB RAM** and **25 GB free disk** on this
machine, using the installed NumPy/BLAS defaults. This is a conservative operator
budget, not a measured requirement or proven capacity guarantee. At most ten
distinct 10,000×2 int64 draw arrays per input game imply 48,610 arrays and
7,777,600,000 raw draw bytes before compression/sharing. Other artifacts add
storage; compressed samples and prefix sharing reduce it. Prior measurements
cannot establish full-run disk or RAM bounds. The first run should be monitored
for runtime, memory and disk growth and failures must remain recorded.

Remaining limitations: historical publication/correction/flex vintages are not
available (strict PIT coverage is zero); final kickoffs and the four-hour finish
lag are reconstruction assumptions; raw-source metadata/receipts are human trust
boundaries; dataset-specific redistribution rights are unresolved; frozen market
midpoint comparison lacks same-cutoff historical quotes; score support/OT and
pooled residuals remain approximate. Nothing demonstrates historical accuracy
or market superiority. The 2024–2025 final holdout stays locked.
