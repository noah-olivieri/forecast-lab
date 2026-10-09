# RF-001 preparation source audit

Independent pre-download audit, 2026-10-08. This audit authorizes a narrowly
pinned public source for local **data preparation only**. It does not authorize
fitting, tuning, a backtest, strict point-in-time claims, or holdout outcomes.
No games CSV, game-data API, or all-season loader was opened by this auditor.

## Immutable source and the pre-download gate

**Decision: safe to retrieve the exact CSV below, subject to byte-identity and
post-download validation.** The source's documentation excludes preseason;
the pinned commit precedes the first 2024 regular-season game. This is evidence
that the version cannot contain genuine 2024–2025 REG/postseason outcomes under
the documented source contract, rather than a claim that its rows were already
counted. Commit timestamps are publisher-controlled metadata, not cryptographic
proof of contemporary public availability. The commit is unsigned. A forged
timestamp or undocumented/fabricated future score remains outside what metadata
alone can authenticate. This is a human-reviewed source trust boundary, not a
machine-verified absence-of-holdout-outcomes claim. Preparation discards
later-season rows using their season/type keys before inspecting outcome fields;
it therefore cannot detect fabricated future scores without opening the locked
outcomes. Do not inspect those fields to try to prove their absence. Validation
of development rows and verification of the pinned blob cannot remove this
remaining source-authenticity assumption.

| Item | Verified official metadata |
|---|---|
| Repository | `nflverse/nfldata` |
| Selection query | Last commit changing `data/games.csv` with author-date through `2024-09-04T23:59:59Z` |
| Commit | `93a5221070bcd1733fe3c55abb48e931b3615241` |
| Author and committer timestamp | `2024-09-04T23:35:17Z` (both) |
| Commit message | `Automated data update` |
| Root tree | `5b0370cfed252a612f312681988652c51a4527ba` |
| `data/` tree | `8251ffe498e2f616244cfca44ec410b15a7595b3` |
| `data/games.csv` blob | `d580dab7aefbef9b9d706363fcb4e862f1aa08fd` |
| Blob mode / size | `100644` / `2,006,863` bytes |
| Immutable raw URL | `https://raw.githubusercontent.com/nflverse/nfldata/93a5221070bcd1733fe3c55abb48e931b3615241/data/games.csv` |

The commit was verified through the [official path-filtered commit query](https://api.github.com/repos/nflverse/nfldata/commits?path=data%2Fgames.csv&until=2024-09-04T23%3A59%3A59Z&per_page=1),
[root tree](https://api.github.com/repos/nflverse/nfldata/git/trees/5b0370cfed252a612f312681988652c51a4527ba), and
[data tree](https://api.github.com/repos/nflverse/nfldata/git/trees/8251ffe498e2f616244cfca44ec410b15a7595b3).
These tree responses were complete (`truncated=false`) and contained metadata,
not score rows. GitHub's `contents` and `git/blobs` APIs can return file contents;
neither was used to audit this CSV.

The [NFL's pre-season announcement](https://www.nfl.com/news/2024-nfl-schedule-release-kansas-city-chiefs-to-host-baltimore-ravens-in-kickoff-game)
dates the 2024 opener September 5. The pinned version is earlier.
The [same-commit DATASETS.md](https://raw.githubusercontent.com/nflverse/nfldata/93a5221070bcd1733fe3c55abb48e931b3615241/DATASETS.md)
explicitly excludes preseason and enumerates only REG, WC, DIV, CON and SB.
Unplayed 2024 schedule rows can therefore exist in this artifact; their
presence is different from outcomes. Their score fields must not be displayed,
summarized, exported or used. Preparation should examine only season/type keys
before discarding later-season rows, and select development fields only for
1999–2023. No current `master`, release URL, redirect to a mutable source,
or all-season nflreadpy loader is an acceptable substitution.

Before parsing, verify both exact size and the Git object identity:
`SHA1(b"blob " + str(len(raw)).encode() + b"\0" + raw)` must equal the blob above.
Compute a SHA-256 over those same bytes for the receipt. The SHA-256 is unknown
until the approved download; it must not be invented or copied from another
version. Parse that verified in-memory buffer rather than reopening its path.
Record fetch time, final requested source URL, commit/blob/size/SHA-256 and the
audit reference. Store the raw source and derived partitions only under ignored
`data/research/`; keep each output season explicitly isolated. The raw pinned
file itself remains a source archive, never an RF-001 input partition.

## Documented fields, timing and reconstruction

The pinned documentation defines season as the starting season, including its
January/February postseason. It describes `gametime` in Eastern time regardless
of stadium location. Combine `gameday` and the source time using
`America/New_York`, including daylight-saving transitions, then serialize UTC.
Never treat it as stadium-local time, fixed EST, or UTC. Missing or invalid times
remain counted exclusions, not noon/midnight imputations. Use explicit REG and
postseason types rather than a week-number threshold.

The [maintainer's current dictionary](https://raw.githubusercontent.com/nflverse/nflreadr/main/data-raw/dictionary_schedules.csv)
corroborates these semantics. It is documentation evidence, not evidence of
the pinned file's exact schema or missingness. The pinned DATASETS document has
stale examples (starts at 2006, legacy game/alternate-ID definitions and older
week limits). Compare actual headers and types against the preparation contract;
do not infer absence of older rows or completeness from those examples.

`home_team` is a designated side, including neutral games. `location` is Home
or Neutral; the shared Giants/Jets venue still uses Home in the dictionary.
Do not infer neutral treatment from a franchise/stadium-name lookup. Report
unexpected location codes, canonical team aliases and alias-version metadata.
Relocated home games and international games need the explicit source flag and
a caveat: an unversioned final flag cannot establish the historical pregame flag.
The final CSV does not supply a full rescheduling, cancellation or correction
history. Final kickoffs may differ from those known at T−24h, including flexes,
weather delays and moves. This preparation is `reconstructed_scores` only.
Publication and first-seen timestamps for old individual observations remain
unknown; the 2024 commit/fetch time must not be stamped as their historical
publication time. The fixed four-hour finish lag is a later reconstruction
assumption, not publication evidence.

No current QB, injury, weather, rest, odds or coach fields should become inputs
merely because they share the CSV. RF-001 preparation projects identities,
schedule times/location and final score labels only. The source's final-score
definitions include the final game result; preserve scores and ties as supplied,
without adding/removing overtime points. A completed label requires both
nonnegative integer scores and an admissible completed-game status; a cancelled
game is not a tie or an unfinished score to be imputed.

## Completeness expectations before retrieval

**Documentary evidence:** the commit follows the end of the 2023 postseason;
the [NFL's 2023 postseason schedule](https://www.nfl.com/schedules/2023/by-week/super-bowl-sunday)
ends February 11, 2024. This makes the full season possible in the chosen file,
not proven present. No field sample or full-file count was used in this audit.

Expected counts are independent checks rather than observed source counts:

| Seasons | Expected REG scheduled | Expected REG completed | Expected WC/DIV/CON/SB |
|---|---:|---:|---|
| 1999–2001 (optional frozen-baseline warm-up) | 248 each | 248 each | 4 / 4 / 2 / 1 |
| 2002–2005 (optional frozen-baseline warm-up) | 256 each | 256 each | 4 / 4 / 2 / 1 |
| 2006–2019 | 256 each | 256 each | 4 / 4 / 2 / 1 |
| 2020 | 256 | 256 | 6 / 4 / 2 / 1 |
| 2021 | 272 | 272 | 6 / 4 / 2 / 1 |
| 2022 | 272 | 271 | 6 / 4 / 2 / 1 |
| 2023 | 272 | 272 | 6 / 4 / 2 / 1 |

The NFL's [1999 attendance accounting](https://nflmediaarchive.nfl.net/nflmedia/News/2000news/Attendance.htm)
reports 248 regular games; its 12-game postseason attendance total is not the
11-game championship-bracket expectation and must **not** be copied as
12 WC/DIV/CON/SB games. Its event classification was not separately audited.
The [official 2002 expansion announcement](https://nflmediaarchive.nfl.net/nflmedia/News/2001news/2002%20OPPONENTS.htm)
describes expansion to 32 clubs, supporting 31×16/2=248 before and 32×16/2=256
after. These arithmetic expectations assume all scheduled games were completed;
the preparation audit must challenge that assumption on discrepancies rather
than silently repair counts. The [NFL's 2021 schedule announcement](https://www.nfl.com/_amp/nfl-owners-approve-enhanced-schedule-with-17-regular-season-games-per-team)
supports 32×17/2=272 from 2021. Championship-bracket totals of 11 and 13 follow
from the respective 12- and 14-team single-elimination fields documented in
the [NFL's 2020 playoff expansion announcement](https://www.nfl.com/news/owners-approve-expanding-postseason-to-14-teams-0ap3000001107961).
The round breakdowns are explicit audit expectations, not source measurements.

The [Bills' official cancellation announcement](https://www.buffalobills.com/news/nfl-says-neutral-site-afc-championship-game-is-possible-bills-bengals-week-17-ga)
establishes the 2022 Week 17 BUF-at-CIN no-contest exception. It must account for
one scheduled game and zero completed labels; source representation (row omitted
or retained with missing scores) is **unverified before download**. Preserve the
observed representation and an exception record with a citation. Do not insert
synthetic score labels or conceal the scheduled-versus-completed difference.
If absent, a documented cancellation record can explain the identity/count gap,
but must be marked externally documented, not an observed source row.

After retrieval, report each season's observed versus expected rows by game
type, completed score count, missing each required field, duplicate IDs/physical
games, score/location validity, teams/aliases and date/time validity. For 2023,
require all 272 completed REG games and all 13 postseason games, including one
SB, rather than stopping at a regular-season total. Count older missing kickoffs
separately and retain the configured development start regardless of missing
warm-up times. Counts alone do not prove correct identities: team appearances,
postseason round identities and cancellation exceptions must reconcile too.
Do not claim exact historical kickoff or publication completeness from this
final-data audit.

## Rights, costs and postseason metadata

Credit Lee Sharpe's nfldata and nflverse, preserve the immutable source citation
and document the transformations. Public raw access needs no key, account or
paid subscription. The verified pinned root has **no LICENSE file**; its README
and DATASETS documentation do not establish a dataset-specific grant. The
[separate nflverse-data repository's CC BY 4.0 license](https://raw.githubusercontent.com/nflverse/nflverse-data/main/LICENSE.md)
must not automatically be applied to this different pinned repository. Raw
redistribution rights remain unresolved; keep the retrieved source and partitions
local and ignored, with attribution. No new paid service or dependency is needed
for this CSV/stdlib timezone preparation.

The [official 2023 playing rules, Rule 16](https://operations.nfl.com/media/rwnj5upg/2023-rulebook_final.pdf)
document that postseason overtime continues until a winner. This validates the
2023 no-final-tie constraint only; it is not a version-specific source for every
older season. Before any eventual fitting/evaluation, supply independently
reviewed season-specific rule references for each included postseason. This
audit does not invent those references or claim to simulate overtime mechanics.

## Gate summary and remaining limits

The metadata gate is complete: only the exact pinned raw CSV, verified against
the Git blob, is cleared for the lead's authorized download. Current source
content, real 2024–2025 results, all-season loaders and statistical evaluations
remain outside scope. Whole-file development completeness, cancellation-row
representation, exact pinned schema, missing kickoff rates and older-season
postseason rule evidence remain post-download checks. Strict historical vintage
evidence remains unavailable even if all those checks pass.

## Post-download follow-up

The lead subsequently reported an exact-size, Git-blob-verified retrieval with
SHA-256 `fb2a5a96e2bd0ddc1b6ddbd487c89857b216114e5ce296214e5b54b6d75bbc43`,
and preparation checks passing for 1999–2023 counts, team appearances and
postseason rounds. All 259 1999 game times were missing, and the cancelled 2022
BUF-at-CIN row was absent. These are post-download observations reported by the
lead, not documentary proof from this pre-download audit or independently
repeated measurements by its author. See [the preparation report](nfl_data_preparation.md)
for final lead verification and artifact references. Real 2024–2025 outcome
fields were not inspected by this auditor.

The original approved gate document is retained unchanged at ignored local path
`data/research/sources/nfldata-93a5221070bcd1733fe3c55abb48e931b3615241/pre-download-audit.md`,
SHA-256 `ac0423810a3e9e600c47aca95e5b00e956f308c83779e29fe3fb8fcb13882cda`.
This dated clarification corrects the earlier suggestion that a later-season
outcome check could run while preserving the locked holdout.
