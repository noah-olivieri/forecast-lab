# NFL data inventory

Audit: 2026-10-08. Foundation only; no model, dashboard, bulk season download,
holdout evaluation, or purchase. Candidate definitions are in
[feature_registry.csv](feature_registry.csv); evaluation and the next build are in
[evaluation_protocol.md](evaluation_protocol.md).

## Evidence and scope

**Documented** means the provider describes a field, history, or release schedule.
**Sample-verified** means a keyless request succeeded and records were inspected.
Neither implies complete season coverage, reliable current feed health, nor a
historical publication vintage. **Unresolved** means not verified in this audit.
Eligibility is separately `eligible`, `reconstructed_historical`, or `unavailable`.

[Audit evidence](audit_samples.json) records URLs, request-start/sample-processing
times (distinguished per record), selected fields,
null counts and hashes. Eight season-specific 2023 CSVs were streamed, retaining
only the first 256 complete records for each measurement (at most a roughly
1 MiB prefix per request). These are ordered, biased samples, not missingness
estimates for a whole season. Empty strings, NA, NaN and null were counted as
missing; a false/zero flag is not missing. Applicability was not inferred from
nulls. Full-season eligible-play denominators and join coverage remain unresolved.
No sampled records are included in the repository; hashes identify the observed
samples, not entire source artifacts. Mutable release URLs may later change.
This evidence is an audit summary, not an independently reproducible raw-data
archive: the counts/hashes cannot be recomputed offline from this JSON alone.
Future ingestion must preserve permitted raw bytes, full-artifact hashes, schemas
and the audit recipe before claiming reproducibility. Do not redownload a changed
release and silently describe it as the originally sampled version.

Schedules were read from `nfldata` commit
`abc9abcd357a64f023e0689d9849dcba3ac4dad1` (2023-12-31T23:55:15Z), not the latest
all-season file. The initial 256 records were from 1999; a second streamed pass
sought the first 256 records of 2023. Older seasons were encountered while seeking,
but only these samples were summarized. The artifact predates the holdout. Four
2023 scores were still absent at that vintage; it cannot supply complete 2023
labels. Its Git commit date alone is not a remote publication receipt or sufficient
strict-vintage proof. No real 2024–2025 outcomes were fetched or inspected.
Documentation about schema changes in those years is metadata, not outcome
inspection. The acquisition's season guard protected these bounded samples; it
did not establish the complete contents of unsampled parts of each release.

Repository inspection: `main` and `forecast-auto` both point to Phase A commit
`1813021`; CLAUDE.md's unmerged status is stale. Research branches from that HEAD.
Existing ingestion keeps only game identity, kickoff, teams, scores and location
in a mutable `nfl_game` table. `load_games()` defaults through the current year;
installed `nflreadpy.load_schedules(seasons)` downloads the all-season artifact
**before** filtering. Do not use either default for holdout-safe research.
The four-hour FINISH_LAG is a completion proxy, not proof of actual completion
or source publication. Existing
features, frozen models and forecast files are not changed by this foundation.

## Sources, fields and coverage

Season ranges below are documented ranges unless explicitly sample-verified.
A start year does not establish every field in every season. Research development
target is 2006–2023; 1999–2005 is only frozen-baseline replay/warm-up if audited.

| Source and official reference | Fields and definitions needed | Supported history and actual verification | Missingness / definition limits |
|---|---|---|---|
| [Schedules/results](https://nflreadr.nflverse.com/reference/load_schedules.html), [machine-readable dictionary](https://raw.githubusercontent.com/nflverse/nflreadr/main/data-raw/dictionary_schedules.csv) | `game_id`, season, game_type, week, Eastern `gameday` + `gametime`, home/away team, final points, `location`; margin = home minus away; total = sum | Pinned artifact contains seasons 1999–2023; 1999 and 2023 samples verified. Complete selected-season coverage still requires audit. | 1999 sample: gametime missing 256/256. 2023: time/ID/location complete, each score missing 4/256. Never impute kickoff as noon. Neutral-designated home is not home advantage. Final QB, referee, roof state and weather are not verified pre-game observations. |
| [nflfastR play-by-play](https://nflreadr.nflverse.com/reference/load_pbp.html), [dictionary](https://nflreadr.nflverse.com/articles/dictionary_pbp.html) | `(game_id, play_id)`, drive, possession/defense, down, distance, field position, clock, play type, yards, sack, turnover, penalty, kicker/receiver/passer IDs; `ep`, `epa`, `cp`, `cpoe` are model-derived | Documented since 1999; 2023 sample verified, 372 columns. | EPA missing 3/256, down 37/256, possession 14/256, passer ID 149/256. Some are structural non-pass/non-scrimmage rows; report applicable denominators separately. Remove deleted/no-play rows under explicit accounting. Imported expected-value model training vintages unresolved. |
| [Player/team stats](https://nflreadr.nflverse.com/reference/load_player_stats.html), [official loader source](https://raw.githubusercontent.com/nflverse/nflreadr/main/R/load_stats.R) | Weekly attempts, carries, targets, receptions, yards, TDs and IDs; sums are opportunity/production, not isolated skill | Official source requests history from 1999; weekly/season summary options documented. Field-by-year coverage unresolved; no actual sample. | Current dictionary is wider than older schemas. Season aggregates contain future games; derive eligible weekly totals instead. Zero production does not prove no participation. |
| [Season rosters](https://nflreadr.nflverse.com/reference/load_rosters.html), [weekly rosters](https://nflreadr.nflverse.com/reference/load_rosters_weekly.html) | `gsis_id`, team, position, status, cross-provider IDs, size/experience; weekly membership rather than latest season status | Season roster documented back to 1920; 2023 season sample verified (36 columns), gsis_id missing 0/256. Weekly range/coverage not verified. | Season-final status and team membership can revise history. Stable IDs do not license using future roster/physical/experience values. Alias/join cardinality audit needed. |
| [Injuries](https://nflreadr.nflverse.com/reference/load_injuries.html), [dictionary](https://nflreadr.nflverse.com/articles/dictionary_injuries.html) | `report_status`, `practice_status`, public primary/secondary injury, `date_modified`, team/week/gsis_id | Documented since 2009; 2023 sample verified (16 columns). | Report status missing 141/256; practice status, ID and date_modified complete in sample. Missing game status may mean no designation, not a confirmed healthy starter. Dictionary says season_type; actual sample uses game_type. Latest modification time is not a complete publication/revision log. |
| [Depth charts](https://nflreadr.nflverse.com/reference/load_depth_charts.html) | Position, formation, `depth_team` rank, gsis_id; rank is a depth-chart assertion, not actual or guaranteed expected starter | Documented since 2001; 2023 sample verified (15 columns), rank/ID missing 0/256. | Sample has week but no publication timestamp. Team depth-chart formation is not a play formation. Actual starters in schedules/participation must not replace expected starters. |
| [PFR snap counts](https://nflreadr.nflverse.com/reference/load_snap_counts.html), [dictionary](https://nflreadr.nflverse.com/articles/dictionary_snap_counts.html) | Game/player offensive, defensive and special-team snaps and percentages | Documented since 2012; 2023 sample verified (16 columns), offense_pct missing 0/256. | Percentage denominator is unit snaps; a zero is valid. Identity mapping and unit sums remain unaudited. Snaps are workload/opportunity, not direct fatigue. |
| [Weekly Next Gen Stats](https://nflreadr.nflverse.com/reference/load_nextgen_stats.html), [dictionary](https://nflreadr.nflverse.com/articles/dictionary_nextgen_stats.html) | Passing time-to-throw (attempts, excludes sacks), air yards, completion above expectation; receiving separation/cushion/YAC; rushing box and efficiency summaries | Documented since 2016. No actual sample: installed loader uses multi-season files; avoid accidentally retrieving holdout rows. | Minimum attempt thresholds omit low-volume players. Weekly aggregates are not full player tracking or route/coverage assignments. NGS model training cutoffs and denominators need audit. |
| [PFR advanced stats](https://nflreadr.nflverse.com/reference/load_pfr_advstats.html), [dictionary](https://nflreadr.nflverse.com/articles/dictionary_pfr_advstats.html) | Passing times pressured, hits, hurries, blitzes, sacks; rushing/receiving/defense advanced summaries | Documented since 2018; weekly passing 2023 sample verified (24 columns), times_pressured missing 0/256. Other types unverified. | Pressure is provider-defined; do not merge with qb_hit or FTN pressure as identical labels. Full weekly availability and denominator needed; season summaries excluded at midseason cutoffs. |
| [FTN public charting](https://nflreadr.nflverse.com/reference/load_ftn_charting.html), [dictionary](https://nflreadr.nflverse.com/articles/dictionary_ftn_charting.html) | Motion, play-action, screen, RPO, box count, blitzers/rushers, drop, interception-worthy throw, QB-fault sack, read progression; `date_pulled` is nflverse retrieval time | Documented since 2022; 2023 sample verified (29 columns), motion/play-action/blitzers/rushers/date_pulled missing 0/256. | Full join coverage unverified; flags require applicability checks. Primary read coding differs in 2022; missing is not necessarily false. No full protection/front/route assignment system. |
| [Participation](https://nflreadr.nflverse.com/reference/load_participation.html), [dictionary](https://nflreadr.nflverse.com/articles/dictionary_participation.html) | Personnel, offensive formation, box count, players on field, pressure, time-to-throw, primary receiver route, man/zone and coverage family | Documented since 2016. NGS through 2022; FTN from 2023. 2023 sample verified (26 columns). | Formation missing 54/256; man/zone and coverage each 128/256; personnel and pressure complete in sample. Full eligible-pass coverage unverified. Primary route is not the whole concept; coverage is not defensive front. Legacy NGS air yards changes after 2023. |

## Publication and T−24h eligibility

Set cutoff from a **versioned kickoff known at the time**. Event time, publication,
provider retrieval, our retrieval and revision-effective time are distinct.
Unknown publication history cannot be repaired by assigning a game's date.
The [nflverse schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html)
documents differing cadences and later statistical corrections. Poll frequency is
not an availability guarantee. Historical latest files remain reconstructed unless
a dated version proves the input existed before cutoff.

| Feed | Documented timing / cutoff implication | Historical classification now |
|---|---|---|
| Schedules and scores | Frequent schedule updates; final points only after completion. Flexed/rescheduled times require vintage selection. | Reconstructed for the broad history; the pinned December 2023 commit identifies a dated version, but its commit date alone proves neither public receipt time nor availability at an earlier cutoff. |
| PBP and derived stats | Cleaned/derived feeds arrive after games and can be corrected later in the week. | Reconstructed latest records; strict needs original snapshots and eligible derived-model artifacts. |
| Roster / depth / injury | Daily pipelines; provider news and practice/game-status releases vary. Later depth format appends timestamped updates rather than week labels. | Historical weekly files insufficient alone; modification timestamps require revision semantics. Current health not sample-verified. |
| NGS, snaps, PFR advanced | Post-game summaries; pipeline polls depend on upstream releases. | Prior-game inputs only after observed release; historical vintage and current health unresolved. |
| FTN public charting | Loader documents charting within 48h after a game; `date_pulled` records extraction, not necessarily first publication. | Can support prior-game live tendencies if actually fetched by cutoff. Latest historical file is reconstructed until original dated pulls are preserved. |
| Participation from 2023 | Public FTN participation arrives only after postseason. | Current-season rolling personnel/coverage unavailable through this feed. Prior-season observations may become eligible after proven release, with a staleness flag. Same-season retrospective tendencies are a separate reconstructed experiment. |

[Official NFL reporting dates](https://amp.nfl.com/news/2026-27-national-football-league-important-dates)
place practice and game-status releases on different days for different kickoff
days. Public injury news can exist before T−24h; the live protocol's rationale
must not be interpreted as all news arriving later. Do not edit that frozen live
protocol here. Neither final inactives nor actual starters are T−24h inputs.
Expected lineup probabilities need timestamped reports plus prior participation,
and calibration against later participation labels in development only.

## Odds, weather, richer sources and rights

| Source | Fields/history/timing | Access, licensing, attribution and known cost | Evidence / gap |
|---|---|---|---|
| nflverse games odds | Moneylines, spread/total lines and prices, with no snapshot/publication time in sampled schema | Keyless; credit Lee Sharpe/nfldata and nflverse. [Repository/README](https://github.com/nflverse/nfldata) did not establish a license for the pinned artifact; redistribution rights unresolved. | Fields verified in 2023 sample. Existing PLAN calls these closing lines; dictionary alone does not establish quote time/book. Exclude from T−24h inputs; later-information benchmark only after quote semantics verified. |
| [The Odds API history](https://the-odds-api.com/liveapi/guides/v4/#get-historical-odds) | Event IDs/kickoff, book, market, paired prices/lines, last_update, snapshot timestamp. Advertised from 2020-06-06; 10-minute then 5-minute snapshots from Sep 2022. Chooses snapshot at/before requested time. | Paid plan and API key required for history; quota 10 credits per region per market. Dollar price unresolved: public pricing did not expose a verifiable amount in this audit. [Terms](https://the-odds-api.com/terms-and-conditions.html) allow research/storage/derived analysis, restrict standalone raw redistribution; attribution appreciated. No signup/purchase. | Documentation only; actual NFL book/game coverage, paired-side completeness and latency unverified. No verified free T−24h sportsbook archive. |
| Kalshi / Polymarket US repo collectors | YES bid/ask, capture timestamp and contract identity; venue rules needed for ties, OT and settlement. [Kalshi historical endpoints](https://docs.kalshi.com/getting_started/historical_data) do not guarantee years of NFL coverage. | Existing keyless collectors; no incremental data subscription for current collection. Archive/display rights require venue-specific review. Trading fees are distinct from data cost; use versioned series metadata if later simulating trades. | Code inspected; no fresh historical API or data-branch audit. No claim of 2006–2023 same-time coverage. Never substitute candles/trades for archived BBO without labeling the change. |
| [Open-Meteo historical forecast](https://open-meteo.com/en/docs/historical-forecast-api), [single runs](https://open-meteo.com/en/docs/single-runs-api) | Wind/gust/direction, temperature, precipitation by stadium and valid time; history advertised around 2021. Run-specific API starts later and can contain hindcasts; initialization is earlier than public distribution. | [Pricing/rights](https://open-meteo.com/en/pricing): free noncommercial access with limits, CC BY 4.0 data attribution; commercial API subscription, historical access requires appropriate plan. Dollar price unresolved. | Documentation only. No verified through-2023 as-issued T−24h weather cohort. Stitched forecast history and reanalysis are not proof of the forecast available then. Prospective fetched forecasts can be eligible. |
| [FTN direct feed](https://ftnfantasy.com/stats/sports-data) | Provider advertises charting/all-22 participation since 2019, expanded participation since 2021, post-game releases and update/approval endpoints. | Advertised starting $3,000/year private, $5,000/year commercial, use-case dependent. Access/rights by agreement; public display permission described for partners (DVOA excluded). No contact/purchase. | Documentation only; richer schema, exact required labels and latency not sampled. Not an assumed solution to every matchup gap. |

Public nflverse release downloads used here require no account/key or payment.
The [nflverse-data license](https://raw.githubusercontent.com/nflverse/nflverse-data/main/LICENSE.md)
is CC BY 4.0, with source-specific overrides: public FTN charting and participation
are CC BY-SA 4.0. Credit FTN Data via nflverse for charting/from-2023 participation,
and NFL NextGenStats via nflverse for earlier participation. Credit PFR/NGS and
nflverse for their aggregates; preserve notices, source versions and modifications.
Repository hosting/code licenses do not establish rights to every upstream feed,
logo, player image or purchased raw artifact. Keep rights unresolved where no
source-specific terms were verified; do not put restricted raw data on the public
`data` branch by default.

## Factors still unsupported and feasibility decision

No verified timely public inputs in this audit directly identify receiver–corner
assignments/shadowing, complete route combinations, leverage/disguise/rotations,
coverage communication errors, defensive fronts/gap responsibility, protection
slides/chips/blitz pickup, stunts, pressure timing, blocking assignments, pursuit
angles or reliable missed-tackle opportunity denominators. Some coarse proxies
exist; they must remain explicitly labeled proxies. Public depth rank is not a
known starting lineup. Injury severity, private recovery restrictions, fatigue,
travel timing, morale and private game plans are not established observations.
Crew assignment timing, transaction vintages, roof decisions and archived weather
runs need separate audits. Aggregate pressure/separation does not identify an
individual blocking or coverage matchup.

**A reduced score model can plausibly operate on timely, free public schedules
and prior final scores**, provided prospective snapshots, completion/publication
checks and missing-data fallback are built and verified. Historical latest data
can support a reproducible reconstructed baseline, not a claimed strict backtest.
The full detailed matchup model cannot yet be supported as a timely public-data
system. Strict historical cohorts may be empty; report that instead of inventing
vintages. Next: the bounded score baseline/harness contract in the evaluation
protocol, followed by field-by-season and vintage audits before adding features.

## Registry conventions

`candidate_id` is stable; change a definition under a new version/ID before
retesting. `experiment_id` groups a future hypothesis test, not an executed run.
`status=planned` means untested, `unavailable` means no verified source satisfying
the required detail/timing. Only a recorded development experiment can assign
`tested_rejected` or `retained`. `historical_eligibility` is a restriction on the
proposed research cohort, not proof that the whole feature has been constructed
or audited. Reconstructed means retrospective research only; unavailable means
an essential input/definition has not been established. Planned live eligibility
is conditional, never implied by status. `evidence_status` separately records
sampled source fields, documentation-only fields, or unresolved inputs. A sampled
source does not verify its derived candidate, required joins, applicability
denominator, or all seasons. Outcome lists use semicolons; each denominator
defines the population to audit before computing that candidate. Registry windows,
shrinkage and interactions remain development choices except RF-001's specified grid.

Source IDs map to the tables above: SCHEDULE, PBP, PLAYER_STATS, ROSTER, DEPTH,
INJURY, SNAPS, NGS, PFR_ADV, FTN_PUBLIC, PARTICIPATION, ODDS_API,
VENUE_SNAPSHOTS and WEATHER_FORECAST. ALL_MANIFESTS means the proposed provenance
records. PUBLIC_REPORTS, VENUE_METADATA, NFL_RULES and RICH_CHARTING_UNVERIFIED are
source requirements, not audited datasets; season coverage, timestamp semantics
and rights remain unresolved. NFL rule versions must come from official rules
applicable to each game. A named commercial provider is not a purchased source.

Every `PIT_*` code requires evidence before cutoff, revision selection and the
prior-game completion rule in the evaluation protocol. Additional requirements:

| Timing code | Requirement |
|---|---|
| PIT_RESULT / PIT_PAST | Final prior result / applicable prior stats published before cutoff; no target-game observations |
| PIT_DERIVED | PIT_PAST plus training/vintage audit of EPA/CP or other supplied learned output |
| PIT_SCHEDULE / PIT_SCHEDULE_META | Schedule and, where used, venue metadata version known before cutoff |
| PIT_LINEUP | Timestamped availability/role observations plus the prior-stat gates for any usage/rating history; actual future starters excluded |
| PIT_PART | Actual participation release by cutoff; from-2023 current-season feed is postseason-only |
| PIT_FTN | Prior FTN charting actually available by cutoff, not merely elapsed provider target latency |
| PIT_PAST_PART / PIT_FTN_PART / PIT_LINEUP_PART | Both named gates; a faster feed cannot make the slower field eligible |
| PIT_PAST_NEWS | Prior-game gate plus dated pre-cutoff public coaching/roster/plan statement |
| PIT_WEATHER | As-issued weather run with public distribution before cutoff and correct kickoff valid time; no reanalysis/hindcasts |
| PIT_LINEUP_WEATHER / PIT_WEATHER_NEWS | Both weather and dated lineup/news gates |
| PIT_CREW | Official crew assignment known before cutoff plus eligible prior crew observations |
| PIT_RULES / PIT_PAST_RULES | Rule version already effective/announced for game, with prior observations if used |
| PIT_RICH | Verified direct labels, documented opportunity denominators and release/revision history from a permitted richer feed |
| PIT_MANIFEST | Quality flags calculated only from eligible input records and training observations |
| PIT_ODDS | Latest valid paired quote at/before cutoff, at most 30 minutes old, same book/market/rules; original snapshot retained; matched models replay at the saved snapshot timestamp |

Multi-source entries inherit all required gates; eligibility cannot be averaged.
Reconstructed experiments explicitly waive vintage proof under a named cohort,
not the chronological game/fold restriction. Availability of a live source still
needs an operational health audit before promotion.

Evidence status values: `sampled_source_fields_only` means some relevant source
columns were checked in a bounded probe, not that the factor was verified;
`documented_sources_only` means no source rows were sampled;
`mixed_sampled_and_documented_inputs` means only part of the input set was probed;
`mixed_sampled_and_unverified_inputs` and `unverified_required_inputs` identify
essential labels/archives still unestablished. A prior injury-status sample does
not establish a practice trajectory, and passing-pressure summaries do not
establish defensive player attribution or blocking causation. Basic penalty
events do not establish all declined/offsetting enforcement labels.

Before a real RF-001 run, produce a through-2023 season audit: expected versus
observed REG/postseason game counts, final-score and kickoff completeness,
duplicate/revision counts, venue/team aliases, and rescheduled/cancelled/suspended
game handling. The December 2023 artifact is only a probe and cannot supply all
2023/postseason labels. Any replacement must be demonstrably holdout-free before
the research runner opens it. Later component audits also need season/team/game
coverage, applicable-play null rates, identifier match rates, join cardinality,
provider definition changes and first-release/correction histories. These checks
have not been performed; the 256-row probes cannot substitute for them.

RF-001 implementation status (2026-10-08): the offline runner and synthetic
evaluation are described in [RF-001](rf001.md). No eligible real research manifest
was present during implementation. No new real data sample was fetched, and the
original bounded audit evidence remains unchanged. The executable baseline
requires only schedule identities/times and completed prior scores; detailed
player/scheme fields and odds are not inputs. Timely public scores can support
prospective operation with archived receipts, but a strict historical schedule/
result vintage archive and full development-season completeness remain unresolved.
