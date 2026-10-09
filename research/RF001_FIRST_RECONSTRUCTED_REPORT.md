# RF-001 first reconstructed development evaluation

Completed 2026-10-08 22:47 PDT.

**Status: both runs completed; integrity verified with a reported diagnostic-count limitation.** This is reconstructed development evidence for outer seasons 2015–2023. No 2024–2025 input or outcome was evaluated. No settings or definitions changed after viewing results. The two required independent-review fixes were committed before executing either evaluation; optional improvements were deferred. Nothing was pushed.

RF-001 improves on league, frozen home-rate and 0.5 in pooled football Brier/log loss and every outer season, but does not improve on frozen Elo overall. Its Elo differences are nominally worse and their 95% intervals include zero. It improves margin CRPS over the league distribution in all nine seasons. Total-CRPS improvement is uncertain. Moneyline results are a separate exploratory reference under unknown timing/book/settlement semantics, not a market-superiority test.

## Review fixes, frozen definitions and verification

Local commit `103766f57198230d97aa5d03b9da8aa90130770f` contains only `src/lab/backtest/nfl_moneyline.py` and `tests/test_nfl_moneyline.py`. The missing scalar-model disclosure was reproduced as a failing output test, then added. The sensitivity test independently derives the registered SHA-256 seed, verifies separation from the primary seed, and hand-checks flagged and unflagged cases: 0.25 difference versus 0.01399038105676658 threshold is flagged; zero difference versus 0.001 is not. A temporary primary-seed-reuse mutation made both tests fail; the registered sensitivity code was restored unchanged. All 15 evaluator cases then passed. No model behavior or frozen definition was altered.

```text
PYTHON_DOTENV_DISABLED=1 UV_OFFLINE=1 UV_CACHE_DIR=/tmp/forecast-foundation-uv-cache uv run --locked --offline pytest -q
323 passed in 44.86s

PYTHON_DOTENV_DISABLED=1 UV_OFFLINE=1 UV_CACHE_DIR=/tmp/forecast-foundation-uv-cache uv run --locked --offline ruff check .
All checks passed!
```

Definitions were approved and committed at `961d58c` before viewing outer results. The primary moneyline label is exactly **“historical moneyline reference; timing and book unknown.”** Primary de-vig is proportional normalization of the two American-odds implied probabilities. Secondary power de-vig solves `q_home**k + q_away**k = 1` with the frozen deterministic bisection recipe; invalid/nonconvergent inputs receive no substitute. RF-001 candidate/fallback and league use `p_home/(p_home+p_away)`, with zero/nonfinite denominators unsupported. Elo/home-rate use their saved scalar unadjusted as an approximation to a conditional decisive-game probability, with no separately identified tie probability. Constant 0.5 is unchanged. Excluding ties does not establish refund settlement. Normalized odds as conditional win probabilities is an explicit assumption. Live `RESEARCH_PROTOCOL.md` remains unchanged.

## Execution and completed-run integrity

Both executions used dotenv disabled, locked offline dependencies and `/usr/bin/caffeinate -i -m`, wrapped in `/usr/bin/time -l`. Outputs were unused before execution; preflight measured 8 GiB RAM and about 80 GiB free disk. Both executions exited 0 and neither was restarted. An initial post-run diagnostic-count assertion failed; its code/log were preserved, then a separately saved verification explained the discrepancy without changing or rerunning either evaluator.

```sh
PYTHON_DOTENV_DISABLED=1 UV_OFFLINE=1 UV_CACHE_DIR=/tmp/forecast-foundation-uv-cache \
/usr/bin/time -l /usr/bin/caffeinate -i -m \
uv run --locked --offline python -m lab.backtest.nfl_score \
  --manifest data/research/inputs/nfldata-93a5221-rf001-2006-2023-v1/execution-manifest.json \
  --run-id rf001-reconstructed-2006-2023-first-v1 --seed 20261008

PYTHON_DOTENV_DISABLED=1 UV_OFFLINE=1 UV_CACHE_DIR=/tmp/forecast-foundation-uv-cache \
/usr/bin/time -l /usr/bin/caffeinate -i -m \
uv run --locked --offline python -m lab.backtest.nfl_moneyline evaluate \
  --run-dir data/research/runs/rf001-reconstructed-2006-2023-first-v1 \
  --odds-manifest data/research/odds/nfldata-93a5221-moneyline-2006-2023-v2/manifest.json \
  --output data/research/runs/rf001-reconstructed-2006-2023-first-v1/historical_moneyline.json
```

The reviewed manifest has exactly 36 schedule/label partitions for 2006–2023 and 4,861 completed game inputs. All models start history in 2006; 2006–2011 is warm-up, 2012–2014 inner-only, and 2015–2023 outer development. Registered nine settings are penalty {0.0003, 0.001, 0.003} × half-life {365, 730, none}; primary draws 10,000, sensitivity draws 20,000, bootstrap replicates 5,000, seed 20261008. No odds enter training, selection, fitting, residuals or saved primary prediction generation. A February 2024 game with season key 2023 belongs to the allowed 2023 postseason, not the 2024 holdout.

The audit verified 68,054 prediction rows (including grid trials), 23,986 scored rows across development roles, all 144,211 immutable JSON content hashes, and 47,020 unique sample-file hashes. Every one of the 4,861 games had `predictions_saved` before `evaluation_released`. Scored values agreed with the hash-pinned saved prediction rows. Exact RF-001 primary draws were reproduced for `2015_01_PIT_NE`, `2019_11_KC_LAC`, `2023_22_SF_KC`. All ten audited protected files retained their starting byte hashes, including snapshot tests, frozen logic/golden tests, existing forecast CSV, Jupyter dependency files and benchmark definitions.

| Artifact | SHA-256 |
| --- | --- |
| Execution manifest | beb96e1167f33dc409eb47e3c7d4005df563ede36127dc9aa4e68a04e7b24fd3 |
| Odds manifest | ce33cc1ddd12aa83847c7f7859a6b13ace2e59b09e13e1cca4ec25b7981a48f4 |
| Saved predictions | ba4eeafc8ebe2135bb49ec4ad3bb7f0ea41e38b85adf562a353e48d40e0f539e |
| Football metrics | 45728f25b7f0d5ef21b559ab33d4fd8ddfe681ee746b41fd70572076a2cda361 |
| Moneyline evaluation | aed61514678be63ead9d37d84d65a751792d267800091311ea050920a1912b05 |

Run artifacts remain ignored and local under `data/research/runs/rf001-reconstructed-2006-2023-first-v1/`. Operator commands, resource logs, preflight, integrity audit code/results and reporting code remain under `data/research/operator/rf001-reconstructed-2006-2023-first-v1/`. Raw metrics, saved forecasts, inputs, fits and residual references are retained for review.

### Football runtime/resources

```text
/Users/noaholivieri/Documents/forecast-lab/data/research/runs/rf001-reconstructed-2006-2023-first-v1
     4346.93 real      4642.21 user       559.22 sys
           858701824  maximum resident set size
                   0  average shared memory size
                   0  average unshared data size
                   0  average unshared stack size
             2414983  page reclaims
                1223  page faults
                   0  swaps
                   0  block input operations
                   0  block output operations
                   1  messages sent
                   1  messages received
                   1  signals received
              479747  voluntary context switches
           133131868  involuntary context switches
           149416683  instructions retired
            58763095  cycles elapsed
            12977088  peak memory footprint
```

### Moneyline runtime/resources

```text
data/research/runs/rf001-reconstructed-2006-2023-first-v1/historical_moneyline.json
     1143.54 real       674.36 user       453.28 sys
          1069056000  maximum resident set size
                   0  average shared memory size
                   0  average unshared data size
                   0  average unshared stack size
             1750835  page reclaims
                 495  page faults
                   0  swaps
                   0  block input operations
                   0  block output operations
                   1  messages sent
                   1  messages received
                   1  signals received
               36884  voluntary context switches
              300462  involuntary context switches
           148513551  instructions retired
            56587813  cycles elapsed
            12649408  peak memory footprint
```

Final allocated run storage: 2.7G. Periodic resource/progress snapshots are retained in `monitor.jsonl`. Process exit codes for football and moneyline were both 0.

## All-game football comparisons: 2015–2023

Target `y=1` home win, `0` away win, `0.5` tie. RF-001 maps to `p_share = p_home + 0.5*p_tie`. Log loss is binary fractional-label loss, clipped only at [1e-6, 1-1e-6]; Brier is unclipped. Margin/total CRPS is in points and supported only by saved full score distributions. Blank cells mean unsupported, not zero. There are nine ties; no binary log-loss values were clipped.

| Model | Scored | Brier | Binary win-share log loss | Margin CRPS | Total CRPS |
| --- | --- | --- | --- | --- | --- |
| RF-001 candidate + registered fallback | 2458 | 0.225980 | 0.645297 | 7.415327 | 7.768034 |
| League score | 2458 | 0.246574 | 0.688124 | 7.894848 | 7.862202 |
| Frozen Elo | 2458 | 0.223733 | 0.640740 |  |  |
| Frozen home-rate | 2458 | 0.246516 | 0.688008 |  |  |
| 0.5 | 2458 | 0.249085 | 0.693147 |  |  |

### Coverage and registered fallback accounting

| Model | Eligible | Predicted | Fallback | Missed | Excluded | Scored | Unlabelled |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RF-001 candidate + registered fallback | 2458 | 2458 | 0 | 0 | 0 | 2458 | 0 |
| League score | 2458 | 2458 | 0 | 0 | 0 | 2458 | 0 |
| Frozen Elo | 2458 | 2458 | 0 | 0 | 0 | 2458 | 0 |
| Frozen home-rate | 2458 | 2458 | 0 | 0 | 0 | 2458 | 0 |
| 0.5 | 2458 | 2458 | 0 | 0 | 0 | 2458 | 0 |

RF-001 has 2,458 candidate forecasts and zero registered fallbacks in the outer cohort; fallbacks would remain part of the primary pipeline comparison. Coverage is 100% of completed, nonvoid inputs, not every originally scheduled event. The retrospective external no-contest `2022_17_BUF_CIN` is separately excluded from all fitting, tuning, residuals and scoring. Global scheduled/retained/external counts are 4,862/4,861/1; outer counts are 2,459/2,458/1. There are no ordinary input exclusions, missing forecasts or unlabelled outer games. The exclusion does not imply cancellation was known at T−24h.

### Registered paired uncertainty

Differences are RF-001 minus comparator; negative favors RF-001. Primary percentile 95% intervals use noncircular four-week blocks within each season, REG followed by postseason in kickoff order; one-week and whole-season sensitivities are also shown. All use 5,000 replicates and seed 20261008. Intervals condition on saved forecasts and do not refit/tune models or include Monte Carlo/selection uncertainty. Each pair retains its registered common-game population; complete-case summaries are descriptive.

| Comparator | Metric | Paired n | RF-001 minus comparator | Four-week CI95 | One-week CI95 | Whole-season CI95 |
| --- | --- | --- | --- | --- | --- | --- |
| League score | brier | 2458 | -0.020595 | [-0.024996, -0.015492] | [-0.026498, -0.014567] | [-0.023715, -0.017336] |
| League score | log_loss | 2458 | -0.042827 | [-0.052304, -0.031749] | [-0.055566, -0.029781] | [-0.049258, -0.035879] |
| League score | margin_crps | 2458 | -0.479521 | [-0.589876, -0.393217] | [-0.596245, -0.362007] | [-0.595984, -0.350414] |
| League score | total_crps | 2458 | -0.094168 | [-0.165633, 0.006456] | [-0.185612, -0.002947] | [-0.210315, 0.046292] |
| Frozen Elo | brier | 2458 | 0.002246 | [-0.000338, 0.005562] | [-0.000921, 0.005243] | [-0.001240, 0.005712] |
| Frozen Elo | log_loss | 2458 | 0.004556 | [-0.001270, 0.011713] | [-0.002372, 0.011150] | [-0.003160, 0.012244] |
| Frozen home-rate | brier | 2458 | -0.020536 | [-0.025036, -0.015434] | [-0.026465, -0.014498] | [-0.023825, -0.017168] |
| Frozen home-rate | log_loss | 2458 | -0.042711 | [-0.052322, -0.031712] | [-0.055593, -0.029618] | [-0.049378, -0.035616] |
| 0.5 | brier | 2458 | -0.023105 | [-0.027731, -0.018542] | [-0.028760, -0.017270] | [-0.026088, -0.020367] |
| 0.5 | log_loss | 2458 | -0.047851 | [-0.057860, -0.037737] | [-0.060155, -0.035180] | [-0.054807, -0.041622] |

### Brier skill and direction

| Comparator | Paired denominator Brier | RF-001 Brier skill | Seasons with lower RF-001 Brier | Pooled Brier improved? |
| --- | --- | --- | --- | --- |
| Frozen Elo | 0.223733 | -0.010041 | 3 | No; nominally worse, interval includes zero |
| 0.5 | 0.249085 | 0.092759 | 9 | Yes |
| Frozen home-rate | 0.246516 | 0.083307 | 9 | Yes |
| League score | 0.246574 | 0.083523 | 9 | Yes |

RF-001 versus league margin CRPS improves in all nine seasons. Total CRPS improves in seven of nine seasons but its primary and whole-season intervals include zero. These comparisons concern complete recipes: RF-001 tunes recency while league uses no decay, so gains cannot be assigned solely to opponent adjustment. Frozen Elo has no native margin distribution, so its margin-CRPS comparison remains unsupported.

### Per-season all-game results

| Season | Model | Scored | Brier | Binary win-share log loss | Margin CRPS | Total CRPS | RF-001 fallback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2015 | RF-001 candidate + registered fallback | 267 | 0.228069 | 0.649781 | 7.461987 | 7.754937 | 0 |
| 2015 | League score | 267 | 0.249565 | 0.692316 | 7.937330 | 7.629155 |  |
| 2015 | Frozen Elo | 267 | 0.225446 | 0.645318 |  |  |  |
| 2015 | Frozen home-rate | 267 | 0.249464 | 0.692104 |  |  |  |
| 2015 | 0.5 | 267 | 0.250000 | 0.693147 |  |  |  |
| 2016 | RF-001 candidate + registered fallback | 267 | 0.223125 | 0.639595 | 6.803242 | 7.134162 | 0 |
| 2016 | League score | 267 | 0.241674 | 0.680199 | 7.303191 | 7.530291 |  |
| 2016 | Frozen Elo | 267 | 0.216829 | 0.625129 |  |  |  |
| 2016 | Frozen home-rate | 267 | 0.241198 | 0.679231 |  |  |  |
| 2016 | 0.5 | 267 | 0.248127 | 0.693147 |  |  |  |
| 2017 | RF-001 candidate + registered fallback | 267 | 0.217979 | 0.625356 | 7.723074 | 8.384616 | 0 |
| 2017 | League score | 267 | 0.244831 | 0.682769 | 8.137389 | 8.072326 |  |
| 2017 | Frozen Elo | 267 | 0.217305 | 0.623027 |  |  |  |
| 2017 | Frozen home-rate | 267 | 0.244616 | 0.682342 |  |  |  |
| 2017 | 0.5 | 267 | 0.250000 | 0.693147 |  |  |  |
| 2018 | RF-001 candidate + registered fallback | 267 | 0.220399 | 0.633583 | 7.408605 | 8.066790 | 0 |
| 2018 | League score | 267 | 0.239849 | 0.676527 | 7.855216 | 8.244549 |  |
| 2018 | Frozen Elo | 267 | 0.221537 | 0.635215 |  |  |  |
| 2018 | Frozen home-rate | 267 | 0.238975 | 0.674751 |  |  |  |
| 2018 | 0.5 | 267 | 0.248127 | 0.693147 |  |  |  |
| 2019 | RF-001 candidate + registered fallback | 267 | 0.225170 | 0.644012 | 7.568039 | 7.652745 | 0 |
| 2019 | League score | 267 | 0.250311 | 0.695679 | 8.303362 | 7.843265 |  |
| 2019 | Frozen Elo | 267 | 0.223962 | 0.643108 |  |  |  |
| 2019 | Frozen home-rate | 267 | 0.250953 | 0.696990 |  |  |  |
| 2019 | 0.5 | 267 | 0.249064 | 0.693147 |  |  |  |
| 2020 | RF-001 candidate + registered fallback | 269 | 0.227394 | 0.648703 | 7.443211 | 7.968040 | 0 |
| 2020 | League score | 269 | 0.252641 | 0.700349 | 7.921541 | 8.244918 |  |
| 2020 | Frozen Elo | 269 | 0.217526 | 0.629975 |  |  |  |
| 2020 | Frozen home-rate | 269 | 0.253133 | 0.701351 |  |  |  |
| 2020 | 0.5 | 269 | 0.249071 | 0.693147 |  |  |  |
| 2021 | RF-001 candidate + registered fallback | 285 | 0.227430 | 0.649631 | 7.881900 | 7.690211 | 0 |
| 2021 | League score | 285 | 0.251111 | 0.697163 | 8.613368 | 7.805231 |  |
| 2021 | Frozen Elo | 285 | 0.234569 | 0.665231 |  |  |  |
| 2021 | Frozen home-rate | 285 | 0.251389 | 0.697727 |  |  |  |
| 2021 | 0.5 | 285 | 0.249123 | 0.693147 |  |  |  |
| 2022 | RF-001 candidate + registered fallback | 284 | 0.231918 | 0.660313 | 6.890848 | 7.720257 | 0 |
| 2022 | League score | 284 | 0.243340 | 0.683317 | 6.951617 | 7.782771 |  |
| 2022 | Frozen Elo | 284 | 0.222040 | 0.636759 |  |  |  |
| 2022 | Frozen home-rate | 284 | 0.243063 | 0.682760 |  |  |  |
| 2022 | 0.5 | 284 | 0.248239 | 0.693147 |  |  |  |
| 2023 | RF-001 candidate + registered fallback | 285 | 0.231476 | 0.654781 | 7.549704 | 7.561277 | 0 |
| 2023 | League score | 285 | 0.245757 | 0.684637 | 8.032738 | 7.629064 |  |
| 2023 | Frozen Elo | 285 | 0.233174 | 0.660267 |  |  |  |
| 2023 | Frozen home-rate | 285 | 0.245749 | 0.684621 |  |  |  |
| 2023 | 0.5 | 285 | 0.250000 | 0.693147 |  |  |  |

### Registered Monte Carlo diagnostic

| Model | Outer checks | Flagged probability components / 9,832 | Flagged CRPS components / 4,916 | Max probability difference | Max CRPS difference (points) |
| --- | --- | --- | --- | --- | --- |
| RF-001 candidate + registered fallback | 2458 | 17 | 1313 | 0.023000 | 0.550045 |
| League score | 2458 | 18 | 1332 | 0.024000 | 0.603600 |

Probability flags use the registered three-standard-error + 0.001 rule; CRPS flags use >0.1 point. There is measurable Monte Carlo variation, especially in individual CRPS values. No seed searching, extra draws or revised threshold was used after viewing these diagnostics. Across all development checks the runner records 39 probability-component flags and 3,932 CRPS-component flags; these broader totals include warm-up/inner roles and are not outer denominators.

## Separate decisive-game historical-moneyline comparison

**Historical moneyline reference; timing and book unknown.** Target `y=1/0` on decisive completed outer games with valid paired moneylines. This is separate from fractional-label all-game scoring. Timing, book/aggregation and settlement semantics are unknown; the source is not a verified close, same-cutoff T−24h benchmark or known consensus. Odds are evaluator-only later-information reference values whose exact timing is unverified. No market-superiority claim follows from these comparisons.

| Coverage item | Count |
| --- | --- |
| excluded_non_outer_odds_rows | 2403 |
| invalid_pairs | 0 |
| missing_pairs | 1 |
| outer_games | 2458 |
| outer_games_with_saved_labels | 2458 |
| partial_pairs | 0 |
| primary_decisive_games | 2448 |
| ties_excluded | 9 |
| valid_moneyline_pairs | 2457 |
| valid_odds_missing_labels | 0 |

Missing/invalid moneyline game IDs: `2017_04_CHI_GB`. Ties excluded: `2016_07_SEA_ARI`, `2016_08_WAS_CIN`, `2018_01_PIT_CLE`, `2018_02_MIN_GB`, `2019_01_DET_ARI`, `2020_03_CIN_PHI`, `2021_10_DET_PIT`, `2022_01_IND_HOU`, `2022_13_WAS_NYG`. Valid-odds missing-label IDs: [].

| Model/reference | Scored | Brier | Binary decisive-game log loss | Margin CRPS | Log-loss clipping count | Missing forecasts | Unsupported probabilities |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RF-001 candidate + registered fallback | 2448 | 0.226854 | 0.645276 |  | 0 | 0 | 0 |
| League score | 2448 | 0.247505 | 0.688155 |  | 0 | 0 | 0 |
| Frozen Elo | 2448 | 0.224514 | 0.640422 |  | 0 | 0 | 0 |
| Frozen home-rate | 2448 | 0.247433 | 0.688010 |  | 0 | 0 | 0 |
| 0.5 | 2448 | 0.250000 | 0.693147 |  | 0 | 0 | 0 |
| Proportional moneyline reference | 2448 | 0.213671 | 0.615462 |  | 0 |  |  |
| Power moneyline sensitivity | 2448 | 0.213726 | 0.615581 |  | 0 |  |  |

Frozen Elo: Saved scalar scored unadjusted as an approximation to the conditional decisive-game win probability; no separately identified tie probability.
Frozen home-rate: Saved scalar scored unadjusted as an approximation to the conditional decisive-game win probability; no separately identified tie probability.

On the primary odds population RF-001 has 2448 candidate predictions, 0 fallback predictions, 2448 candidates scored and 0 fallbacks scored. All-model complete-case count is 2448 and is descriptive only. Registered football pairwise game-ID lists in the evaluator agree with the football report. Full eligible coverage, missingness and tie exclusions stay visible; no selection rule changed after results.

On this decisive subset RF-001 has nominally lower Brier/log loss than league, home-rate and 0.5, and nominally higher losses than Elo and both moneyline references. The stored moneyline uncertainty comparisons below are each model versus reference; they do not substitute for the registered all-game model-versus-model comparisons above.

### Paired model minus proportional reference

| Model | Metric | Paired n | Model minus reference | Four-week CI95 | One-week CI95 | Whole-season CI95 |
| --- | --- | --- | --- | --- | --- | --- |
| RF-001 candidate + registered fallback | brier | 2448 | 0.013182 | [0.010172, 0.018582] | [0.008582, 0.017619] | [0.008240, 0.018255] |
| RF-001 candidate + registered fallback | log_loss | 2448 | 0.029813 | [0.022900, 0.041767] | [0.019576, 0.039595] | [0.019088, 0.040958] |
| League score | brier | 2448 | 0.033834 | [0.028740, 0.040482] | [0.027446, 0.040023] | [0.028492, 0.039773] |
| League score | log_loss | 2448 | 0.072693 | [0.061153, 0.087519] | [0.058363, 0.086370] | [0.061020, 0.085354] |
| Frozen Elo | brier | 2448 | 0.010843 | [0.008669, 0.014778] | [0.007341, 0.014442] | [0.006109, 0.014677] |
| Frozen Elo | log_loss | 2448 | 0.024960 | [0.020197, 0.033622] | [0.017140, 0.032913] | [0.014784, 0.033554] |
| Frozen home-rate | brier | 2448 | 0.033762 | [0.028711, 0.040513] | [0.027343, 0.039983] | [0.028380, 0.039878] |
| Frozen home-rate | log_loss | 2448 | 0.072548 | [0.061094, 0.087542] | [0.058222, 0.086336] | [0.060682, 0.085505] |
| 0.5 | brier | 2448 | 0.036329 | [0.031186, 0.043433] | [0.029866, 0.042627] | [0.031246, 0.041212] |
| 0.5 | log_loss | 2448 | 0.077685 | [0.065985, 0.093262] | [0.063314, 0.091989] | [0.066512, 0.088311] |

### Fixed secondary power-de-vig sensitivity

The power method remains secondary and was not selected based on scores. Failed power inputs are not replaced by proportional values. Model forecasts, ties and primary selection rules are unchanged.

| Model | Metric | Paired n | Model minus power reference | Four-week CI95 | One-week CI95 | Whole-season CI95 |
| --- | --- | --- | --- | --- | --- | --- |
| RF-001 candidate + registered fallback | brier | 2448 | 0.013128 | [0.009976, 0.018688] | [0.008402, 0.017666] | [0.008003, 0.018374] |
| RF-001 candidate + registered fallback | log_loss | 2448 | 0.029695 | [0.022315, 0.042031] | [0.019069, 0.039872] | [0.018583, 0.041325] |
| League score | brier | 2448 | 0.033779 | [0.028465, 0.040682] | [0.027144, 0.040218] | [0.028340, 0.039858] |
| League score | log_loss | 2448 | 0.072574 | [0.060245, 0.088121] | [0.057550, 0.087055] | [0.060596, 0.085691] |
| Frozen Elo | brier | 2448 | 0.010788 | [0.008509, 0.014843] | [0.007159, 0.014490] | [0.006025, 0.014706] |
| Frozen Elo | log_loss | 2448 | 0.024841 | [0.019742, 0.033823] | [0.016544, 0.033084] | [0.014543, 0.033472] |
| Frozen home-rate | brier | 2448 | 0.033707 | [0.028430, 0.040700] | [0.027070, 0.040155] | [0.028168, 0.039949] |
| Frozen home-rate | log_loss | 2448 | 0.072429 | [0.060246, 0.088141] | [0.057281, 0.086924] | [0.060228, 0.085859] |
| 0.5 | brier | 2448 | 0.036274 | [0.030895, 0.043641] | [0.029577, 0.042863] | [0.031008, 0.041358] |
| 0.5 | log_loss | 2448 | 0.077566 | [0.065215, 0.093926] | [0.062358, 0.092619] | [0.066025, 0.088599] |

### Per-season decisive-game results

| Season | Model | Scored | Brier | Binary log loss | Brier minus proportional | Log loss minus proportional | Brier minus power | Log loss minus power |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2015 | RF-001 candidate + registered fallback | 267 | 0.228108 | 0.650114 | -0.000557 | 0.001296 | -0.001000 | 0.000156 |
| 2015 | League score | 267 | 0.249591 | 0.692370 | 0.020926 | 0.043552 | 0.020483 | 0.042412 |
| 2015 | Frozen Elo | 267 | 0.225446 | 0.645318 | -0.003219 | -0.003500 | -0.003662 | -0.004640 |
| 2015 | Frozen home-rate | 267 | 0.249464 | 0.692104 | 0.020799 | 0.043286 | 0.020356 | 0.042146 |
| 2015 | 0.5 | 267 | 0.250000 | 0.693147 | 0.021335 | 0.044329 | 0.020892 | 0.043189 |
| 2016 | RF-001 candidate + registered fallback | 265 | 0.224832 | 0.639158 | 0.007805 | 0.017584 | 0.007905 | 0.018203 |
| 2016 | League score | 265 | 0.243462 | 0.680029 | 0.026436 | 0.058455 | 0.026536 | 0.059074 |
| 2016 | Frozen Elo | 265 | 0.218462 | 0.624611 | 0.001436 | 0.003036 | 0.001535 | 0.003655 |
| 2016 | Frozen home-rate | 265 | 0.243000 | 0.679089 | 0.025974 | 0.057514 | 0.026073 | 0.058133 |
| 2016 | 0.5 | 265 | 0.250000 | 0.693147 | 0.032974 | 0.071573 | 0.033073 | 0.072192 |
| 2017 | RF-001 candidate + registered fallback | 266 | 0.218538 | 0.626571 | 0.015472 | 0.033342 | 0.015794 | 0.034222 |
| 2017 | League score | 266 | 0.245031 | 0.683172 | 0.041966 | 0.089943 | 0.042288 | 0.090823 |
| 2017 | Frozen Elo | 266 | 0.218001 | 0.624626 | 0.014936 | 0.031397 | 0.015258 | 0.032277 |
| 2017 | Frozen home-rate | 266 | 0.244843 | 0.682798 | 0.041777 | 0.089569 | 0.042099 | 0.090449 |
| 2017 | 0.5 | 266 | 0.250000 | 0.693147 | 0.046934 | 0.099918 | 0.047257 | 0.100798 |
| 2018 | RF-001 candidate + registered fallback | 265 | 0.221744 | 0.632246 | 0.009351 | 0.018705 | 0.009253 | 0.018182 |
| 2018 | League score | 265 | 0.241589 | 0.676260 | 0.029196 | 0.062718 | 0.029098 | 0.062196 |
| 2018 | Frozen Elo | 265 | 0.222856 | 0.633935 | 0.010464 | 0.020393 | 0.010366 | 0.019871 |
| 2018 | Frozen home-rate | 265 | 0.240740 | 0.674535 | 0.028348 | 0.060993 | 0.028249 | 0.060471 |
| 2018 | 0.5 | 265 | 0.250000 | 0.693147 | 0.037607 | 0.079605 | 0.037509 | 0.079083 |
| 2019 | RF-001 candidate + registered fallback | 266 | 0.226004 | 0.643866 | 0.011885 | 0.027569 | 0.011649 | 0.026995 |
| 2019 | League score | 266 | 0.251279 | 0.695745 | 0.037160 | 0.079448 | 0.036925 | 0.078875 |
| 2019 | Frozen Elo | 266 | 0.224790 | 0.642893 | 0.010671 | 0.026596 | 0.010435 | 0.026022 |
| 2019 | Frozen home-rate | 266 | 0.251877 | 0.696964 | 0.037757 | 0.080667 | 0.037522 | 0.080093 |
| 2019 | 0.5 | 266 | 0.250000 | 0.693147 | 0.035881 | 0.076850 | 0.035645 | 0.076277 |
| 2020 | RF-001 candidate + registered fallback | 268 | 0.228207 | 0.648581 | 0.026340 | 0.058629 | 0.026699 | 0.059309 |
| 2020 | League score | 268 | 0.253624 | 0.700457 | 0.051756 | 0.110505 | 0.052115 | 0.111184 |
| 2020 | Frozen Elo | 268 | 0.218139 | 0.629292 | 0.016271 | 0.039341 | 0.016631 | 0.040020 |
| 2020 | Frozen home-rate | 268 | 0.254059 | 0.701345 | 0.052192 | 0.111394 | 0.052551 | 0.112073 |
| 2020 | 0.5 | 268 | 0.250000 | 0.693147 | 0.048132 | 0.103196 | 0.048492 | 0.103875 |
| 2021 | RF-001 candidate + registered fallback | 284 | 0.228097 | 0.649296 | 0.010439 | 0.026110 | 0.009916 | 0.024784 |
| 2021 | League score | 284 | 0.252033 | 0.697255 | 0.034376 | 0.074069 | 0.033853 | 0.072742 |
| 2021 | Frozen Elo | 284 | 0.234930 | 0.663806 | 0.017272 | 0.040620 | 0.016749 | 0.039294 |
| 2021 | Frozen home-rate | 284 | 0.252260 | 0.697716 | 0.034603 | 0.074530 | 0.034080 | 0.073203 |
| 2021 | 0.5 | 284 | 0.250000 | 0.693147 | 0.032343 | 0.069961 | 0.031820 | 0.068635 |
| 2022 | RF-001 candidate + registered fallback | 282 | 0.233634 | 0.660395 | 0.024347 | 0.055433 | 0.024663 | 0.056631 |
| 2022 | League score | 282 | 0.245046 | 0.683207 | 0.035759 | 0.078244 | 0.036075 | 0.079442 |
| 2022 | Frozen Elo | 282 | 0.223578 | 0.636285 | 0.014291 | 0.031322 | 0.014606 | 0.032520 |
| 2022 | Frozen home-rate | 282 | 0.244760 | 0.682632 | 0.035473 | 0.077669 | 0.035788 | 0.078868 |
| 2022 | 0.5 | 282 | 0.250000 | 0.693147 | 0.040713 | 0.088184 | 0.041028 | 0.089383 |
| 2023 | RF-001 candidate + registered fallback | 285 | 0.231643 | 0.655246 | 0.013004 | 0.028276 | 0.012739 | 0.027445 |
| 2023 | League score | 285 | 0.245763 | 0.684650 | 0.027125 | 0.057679 | 0.026860 | 0.056849 |
| 2023 | Frozen Elo | 285 | 0.233174 | 0.660267 | 0.014536 | 0.033296 | 0.014271 | 0.032466 |
| 2023 | Frozen home-rate | 285 | 0.245749 | 0.684621 | 0.027110 | 0.057650 | 0.026845 | 0.056820 |
| 2023 | 0.5 | 285 | 0.250000 | 0.693147 | 0.031362 | 0.066177 | 0.031096 | 0.065346 |

### Per-season reference scores

| Season | Decisive n | Proportional Brier | Proportional log loss | Power Brier | Power log loss |
| --- | --- | --- | --- | --- | --- |
| 2015 | 267 | 0.228665 | 0.648818 | 0.229108 | 0.649958 |
| 2016 | 265 | 0.217026 | 0.621574 | 0.216927 | 0.620955 |
| 2017 | 266 | 0.203066 | 0.593229 | 0.202743 | 0.592349 |
| 2018 | 265 | 0.212393 | 0.613542 | 0.212491 | 0.614064 |
| 2019 | 266 | 0.214119 | 0.616297 | 0.214355 | 0.616870 |
| 2020 | 268 | 0.201868 | 0.589952 | 0.201508 | 0.589272 |
| 2021 | 284 | 0.217657 | 0.623186 | 0.218180 | 0.624513 |
| 2022 | 282 | 0.209287 | 0.604963 | 0.208972 | 0.603764 |
| 2023 | 285 | 0.218638 | 0.626970 | 0.218904 | 0.627801 |

Reference season losses above are recovered arithmetically from the saved model losses and paired differences; both references use the same season population in this completed run. No prediction or benchmark evaluation was rerun.

### Conditional-probability sensitivity

| Model | Outer decisive checks | Flagged | Maximum conditional-probability difference | Repeat draws |
| --- | --- | --- | --- | --- |
| RF-001 candidate + registered fallback | 2448 | 5 | 0.022987 | 20000 |
| League score | 2448 | 6 | 0.023754 | 20000 |

Every repeat seed was checked against the corresponding runner-recorded independent `mc-sensitivity-v1` seed and differs from the saved primary seed. This ratio-specific check is separate from the runner component checks. Flagged cases remain reported and scored under the frozen recipe; there was no seed search or retrospective deletion.

### Diagnostic-count provenance limitation

The initial post-run audit recomputed ratio thresholds directly from the serialized integer repeat count and failed. Investigation found 200 of 4,896 checks have a reported `repeat_decisive_draws` one below the actual count: the evaluator uses `int(20000*(p_home+p_away))`, and floating representation can lie just below an integer. Exact reproduction of RF-001 `2015_04_HOU_ATL` produced 19,357 decisive draws and the registered independent seed, while the product was 19,356.999999999996 and the report integer 19,356. The saved threshold matched the committed floating-count calculation. All 4,896 seeds matched the runner independent sensitivity records and differed from primary seeds; all thresholds matched either the reported count or that count plus one. The largest threshold discrepancy from the reported integer was 0.000000161251, and no flag changes using either count. Aggregate saved-prediction and proportional-reference losses were independently recomputed. Hashes and football pairwise populations remained valid. This is a diagnostic-count reporting defect, not evidence of changed primary predictions or score calculations. It is disclosed and deferred for separate review to respect the two-fix scope; no evaluator output, source, definition or production logic was changed after results. Original `moneyline_integrity.log` failure and `moneyline_integrity_v2.log` findings are preserved.

## Limitations and stopping point

This is reconstructed development evidence, not strict point-in-time or final holdout evidence. Strict historical PIT coverage remains zero: final kickoffs, final corrected labels and the four-hour finish lag lack historical publication/correction/flex vintages. Cancellation exclusion is retrospective and coverage is conditional on completed nonvoid games. Score draws are a rounded/nonnegative paired-residual approximation, not a full football or historical-overtime simulation. Monte Carlo diagnostics show individual-score numerical variation, and bootstrap intervals omit refitting, tuning and simulation uncertainty. The unknown moneyline timing/book/aggregation/settlement assumptions prevent same-cutoff and superiority claims; excluding ties does not establish settlement rules. No prediction-market midpoint benchmark is available at matched historical cutoffs, and no P&L or fee/fill claim is made. Redistribution rights remain unresolved; research inputs and artifacts stay local and ignored.

Both executions completed without restart; the separately preserved post-run audit revision documents the diagnostic-count limitation. No method was chosen or changed after viewing outcomes. The 2024–2025 holdout remains locked. Protected snapshot changes remain unstaged; the report is left uncommitted for review. Stop here: no push, new features, additional experiment or holdout evaluation is authorized by this report.

