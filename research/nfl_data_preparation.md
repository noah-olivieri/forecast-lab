# NFL development-data preparation

Execution-policy follow-up: [the evaluation-gate report](nfl_evaluation_gates.md)
supersedes this report's pending warm-up/cancellation/rules decisions for the
first proposed backtest. The original 1999–2023 preparation archive and its
measurements below remain unchanged; the new execution input is 2006–2023 only.

2026-10-08. Data preparation only: no model fit, hyperparameter selection,
historical backtest, market comparison or holdout outcome access. This report
does not change the [evaluation protocol](evaluation_protocol.md). Source-audit,
implementation and read-only review agents had separate file ownership; the lead
independently verified the downloaded identity, prepared inputs and replay.

## Source approval and preservation

The [independent source audit](rf001_preparation_source_audit.md) completed before
the single games CSV download. The lead checked the pinned GitHub commit and tree
metadata and the same-commit documentation before downloading. The exact source is
[nfldata games.csv at 93a5221](https://raw.githubusercontent.com/nflverse/nfldata/93a5221070bcd1733fe3c55abb48e931b3615241/data/games.csv),
committed `2024-09-04T23:35:17Z`, before the 2024 regular-season opener. Its pinned
documentation excludes preseason. Credit Lee Sharpe and nflverse.

Verified raw size: **2,006,863 bytes**. Verified Git blob:
`d580dab7aefbef9b9d706363fcb4e862f1aa08fd`. SHA-256:
`fb2a5a96e2bd0ddc1b6ddbd487c89857b216114e5ce296214e5b54b6d75bbc43`.
The tool verifies blob identity, size and SHA-256 before parsing the same buffered
bytes. It examines season first and discards unrequested rows before selecting or
converting their score fields. No current all-season loader was used. Holdout
outcomes were not inspected, summarized, exported or evaluated.

The source and receipts live under ignored
`data/research/sources/nfldata-93a5221070bcd1733fe3c55abb48e931b3615241/`.
`download.json` records the fetch, source URL and approved gate/document hashes;
`pre-download-audit.md` preserves the exact original approval bytes even though
the working audit document later clarified its trust-boundary limitation.
`source-receipt.json` records the cancellation exception and reviewed 2023 rule
reference. The commit is unsigned and its timestamp is publisher-controlled.
These checks authenticate the selected bytes, not the truth of the publisher's
metadata or the absence of fabricated future values in discarded rows. The
receipt is an independently reviewed human assertion. No result inspection was
used to strengthen the holdout-safety claim.

## Preparation contract and reproduction

`src/lab/backtest/prepare_nfl_scores.py` is an offline CLI/API. It uses a local
audited receipt and CSV and requires explicit allowed seasons (1999–2023 only).
It performs no download, fit, tuning or dotenv loading. No new dependency was
needed: CSV, hashes and timezone conversion use the standard library. Existing
Jupyter development-dependency changes remain untouched.

The final build is
`data/research/inputs/nfldata-93a5221-development-v2/manifest.json`.
To reproduce from the preserved local source, use a **new** build ID:

```sh
PYTHON_DOTENV_DISABLED=1 UV_OFFLINE=1 uv run python -m lab.backtest.prepare_nfl_scores \
  --raw data/research/sources/nfldata-93a5221070bcd1733fe3c55abb48e931b3615241/games.csv \
  --receipt data/research/sources/nfldata-93a5221070bcd1733fe3c55abb48e931b3615241/source-receipt.json \
  --build-id nfldata-93a5221-review-replay \
  --seasons 1999 2000 2001 2002 2003 2004 2005 2006 2007 2008 2009 2010 2011 2012 2013 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023
```

Outputs are write-once under ignored `data/research/inputs/`. Each season has
scoreless `schedules-Y.csv`, separate `labels-Y.csv`, `source-rows-Y.json` and
`exclusions-Y.json`. The build adds an exact-byte receipt, `audit.json` and a
manifest containing hashes, source/alias/extractor provenance, Python version and
the actual timezone database hash. The 1999–2005 partitions are explicitly
`baseline_warmup`; development remains 2006–2023. Their presence does not amend
warm-up or baseline replay rules.

Only identities, schedule/type/location and final labels are projected into
RF-001 inputs. Retrospective raw source rows preserve additional fields for
audit; QB, coaching, odds, weather, rest and other extra columns do not become
features. Required headers, integer scores, positive weeks, franchises, location,
date/time, duplicate/overlapping games and full-season structural counts must
validate before output creation. DST folds and nonexistent Eastern times fail;
missing times stay blank with exclusions. Failures after creating the output
directory leave `failure.json`. Existing builds, hidden paths and symlink paths
are refused.

All old observations have blank publication/first-seen times and
`availability_evidence=retrospective_fetch`, with the actual retrieval time.
Eastern source times become UTC using `America/New_York`; final source kickoffs
are reconstructed rather than known historical T−24h schedule revisions. No
four-hour finish lag is presented as publication evidence.

## Verified full-file development coverage

These are **full selected-season structural checks**, replacing mere sampled
field availability for this pinned source. They do not independently authenticate
every source identity, score or exact historical kickoff. The source has 46
columns; the JSON audit reports field-by-field missingness for every season.

| Seasons | REG source/completed per season | Postseason per season | Missing kickoff times |
|---|---:|---:|---:|
| 1999 | 248 | 11 | 259, all games |
| 2000–2001 | 248 | 11 | 0 |
| 2002–2019 | 256 | 11 | 0 |
| 2020 | 256 | 13 | 0 |
| 2021 | 272 | 13 | 0 |
| 2022 | 271 completed; 272 scheduled externally | 13 | 0 in source rows |
| 2023 | 272 | 13 | 0 |

The 31-franchise pre-expansion and 32-franchise later appearance counts reconcile;
BUF and CIN have 16 completed appearances in 2022. WC/DIV/CON/SB counts are
4/4/2/1 before 2020 and 6/4/2/1 thereafter. The 2023 postseason includes
`2023_22_SF_KC`, played in February 2024 and retained in starting-year season 2023.
No completed score is missing among the 6,706 retained rows. Dates, source scores,
canonical aliases, location flags, physical duplicates and team overlaps passed
validation; this does not prove that final neutral flags were known pregame.

The canceled 2022 BUF-at-CIN game is **absent from this source**. An independently
documented `2022_17_BUF_CIN` exception accounts for the scheduled-versus-completed
gap. It is a ledger entry, not a downloaded source row or a fabricated schedule,
kickoff or label. A future evaluation needs an explicit cancellation/denominator
decision before fitting. The source's omission alone cannot implement it.

Development 2006–2023 contains **4,655 REG + 206 postseason = 4,861 completed
games**, all with recorded times. Warm-up contains 1,845 labels, including 259
1999 missing-time exclusions. The existing loader accepts the season-isolated
manifest: 6,706 labels, 6,447 schedule targets with kickoffs and 259 exclusions.
Strict point-in-time target coverage from these vintages is **zero**.

See [the machine-readable audit](nfl_data_preparation_audit.json) for source and
manifest hashes, every season's counts/missingness and measured build/replay.
The lead checked all 50 partition and 52 audit-artifact hashes, exact saved receipt
bytes and all 6,706 selected source projections. A second final-code build was
byte-identical across all 103 generated files. Preparation took 2.88 seconds,
replay 2.87 seconds, and each generated build used 11,839,174 bytes before adding
the separate lead verification note. These are local preparation measurements,
not historical accuracy or RF-001 model-runtime measurements. The earlier v1
build remains preserved locally; v2 records the final positive-week validation.

## Tests, review and remaining gates

34 synthetic preparation cases cover the receipt-before-read gate, locked years,
byte identity/replay, scoreless outputs, completeness and per-team appearances,
postseason round totals including a missing-SB failure, franchise expansion,
aliases, neutral games/ties, DST, cancellations retained/omitted/partial, missing
times, invalid scores, week zero, headers/malformed rows, duplicate/overlapping
games across seasons and write-once/symlink protection. Tests have no network
calls and disable dotenv. Failing tests preceded the implementation and the
subsequent confirmed fixes. The independent reviewer remained read-only and
checked the real derived inputs without fitting or holdout access; the lead
performed separate integration and replay checks.

The review concern that a pre-opener snapshot might contain 2024 preseason
results was resolved by the pinned documentation's explicit preseason exclusion.
Unsigned metadata and receipt assertions remain a limitation. A claim that this
audit proves absence of fabricated future scores was corrected rather than
verified by opening holdout fields. Counts, franchise appearances and round
checks establish structural completeness; they do not establish publication
timing or an independent game-by-game external truth set.

Prepared public inputs are sufficient for the **reconstructed score-input
contract**, with the stated exclusions. A historical evaluation is not ready:
review season-specific postseason rule references for every included season;
decide the canceled-game denominator policy and 1999 warm-up exclusions before
any evaluation; then freeze the reviewed input manifest and protocol decisions.
Only the 2023 official rule reference is currently supplied. `runner_ready=false`
is advisory: the existing RF-001 runner does **not** enforce that flag, although
its missing-rule-metadata validation currently prevents this real build from
running. Do not infer readiness merely by filling the flag or rule fields.

Historical publication/correction and rescheduling vintages remain unavailable;
no strict T−24h claim follows from complete final-score rows. Dataset-specific
redistribution rights for this pinned nfldata repository remain unresolved, so
raw/derived data stay local and ignored. No paid access, dependency installation,
live-workflow change, statistical redesign or 2024–2025 outcome access occurred.
No model superiority or historical accuracy has been measured.
