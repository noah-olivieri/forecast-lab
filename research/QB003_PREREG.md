# QB-003: QB quality adjustment, T-24h expected starter (pre-registration)

Date: 2026-10-12. Committed before any QB-003 code or results exist.
Rules: DECISIONS.md entry of 2026-10-11 applies in full.

## My words
"Because the Elo is already taken into account, the starter's normal quality, adding a
bonus wouldn't make sense."

## Design (drafted by Claude, accepted by Noah)

Base model: frozen elo-538-default-v0, run through the verified fast replay (9e3e083).
QB-003 is a replay hook. Adjustments change only the forecast, never rating updates.

Comparator: frozen Elo. QB-001 and QB-002 are starter-known exploratory results and were
never accepted, so frozen Elo is the current best.

Seasons: forecasts for 2010-2023 only. 2009 has no injury timestamps. 2024-2025 stay locked.
History inputs may use play-by-play from 2007 onward.

Cutoff for each game: kickoff minus 24 hours. Only information available before the
cutoff is used. Past games count as history only if they finished before the cutoff
(the replay's existing rule).

Usual starter: QB-001 definition, the QB with the most starts in the team's last 8
games before the cutoff.

Expected starter (DECISIONS rule 2):
- If the usual starter's final injury status is Out or Doubtful and its date_modified is
  before the cutoff, the expected starter is the team's other QB with the most dropbacks
  in its last 8 games. If there is none, the expected starter is treated as a rookie.
- Any other case (Questionable, no status, missing date_modified, or date_modified after
  the cutoff): the expected starter is the usual starter.

QB quality: ANY/A per dropback, from nflverse play-by-play, model-free.
ANY/A = (passing yards + 20 x passing TD - 45 x interceptions - sack yards) /
(pass attempts + sacks). For each QB, use dropbacks from the previous 3 seasons plus this
season's games that finished before the cutoff. Shrink toward a prior:
    q = (sum of ANY/A numerator + k x prior) / (dropbacks + k), with k = 200.

Prior: dropback-weighted mean ANY/A over the first 100 career dropbacks of QBs who
debuted after 1999 and before the forecast season. Recomputed each season (rolling).
A QB with no dropbacks gets the prior.

Adjustment, for each team: beta x (q_expected - q_usual) Elo points. Zero when the
expected starter is the usual starter.

Definitions:
- In this document a dropback means a pass attempt or a sack. Scrambles are not
  counted. Two-point conversion plays are excluded everywhere.
- Both regular-season and postseason games count as history and as forecast games,
  as in QB-001.
- Ties for "most dropbacks": the QB with the more recent dropback wins. If still tied,
  the lowest nflverse player ID wins.

Walk-forward screening: for each season s from 2013 to 2023, pick beta from
{0, 5, 10, ..., 100} by lowest Brier on all games from 2010 through s-1, then forecast
season s with that beta. Ties go to the smaller beta.

## Decision rule (DECISIONS rule 6)
Include QB-003 only if, over the 2013-2023 walk-forward forecasts:
- mean Brier improves on frozen Elo by at least 0.0005, AND
- it is better than frozen Elo in at least 6 of 11 seasons.
Otherwise it is excluded as null. Worse on average means harmful, excluded and reported.
A paired 95% CI is reported as description, not as the decision.

## Reported
Overall and per-season Brier and log loss for QB-003 and frozen Elo, the beta chosen for
each season, the share of games with a nonzero adjustment, weeks 1-4 versus later weeks,
and SHA-256 hashes of every input file.

## Known limits
- Label: T-24h valid, if nflverse injury timestamps are accurate.
- Benchings and other non-injury starter changes are not predicted. This matches what
  was knowable at T-24h.
- nflverse files are rebuilt over time. Box-score corrections are disclosed, not
  disqualifying.
- This is the first of at most 3 development tests. Screening is not confirmation; the
  2024-2025 holdout is.
