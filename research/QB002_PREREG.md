# QB-002 pre-registration: separate new starters from backups (v2)

Date: 2026-10-09. Written and pushed before any QB-002 code or results exist.

Motivation (my words): "How can we make this model better and account for rookie
quarterbacks that enter during the offseason?"

Background: QB-001 flagged any starter who was not the team's usual starter. The flag
fired in 55% of weeks 1-4 games and gained almost nothing there, likely because most of
those flags were new starters after an offseason change, not backups. One penalty had to
cover both groups.

Hypothesis: Not flagging new starters will improve on QB-001.

Rule: Same as QB-001, with one change. A starter who has started every one of this
team's earlier games this season (regular season and playoffs) is not flagged. Week 1 is
therefore never flagged. Missing QB IDs earlier this season are skipped, as in QB-001.

Penalty: grid of 0 to 8 points of spread in 1-point steps, 25 Elo per point, chosen by
lowest all-game Brier on 2006-2014 (ties y = 0.5). Ties go to the smaller penalty.

Primary test: QB-002 vs QB-001 on 2015-2023, paired Brier difference with the registered
paired block-bootstrap CI, all games. Success means the 95% CI excludes zero in QB-002's
favor. Anything else is a null result.

Also reported: QB-002 vs frozen Elo (all games and moneyline subset), QB-002 vs the
moneyline reference, chosen penalty, flag rate, per-season results, and weeks 1-4 vs
later weeks.

Limitations: Same lookahead as QB-001. A backup who starts every game from week 1 (for
example after a preseason injury) is never flagged during that stint. This is the third
test on 2015-2023, so it is development evidence only.

## Clarifications

Added before the first push, before any QB-002 code or results exist.

1. The exemption lasts past week 1. A backup who starts every game from week 1, for
   example weeks 1-6 after a preseason injury, is never flagged during that run.
2. If every earlier game this season has a missing QB ID, the starter counts as having
   started every one, so he is not flagged. This is the same logic as week 1. It can only
   happen in 2023, where the 8 missing IDs are.
3. Each model uses its own penalty in the primary test. QB-001 stays at its saved 2
   points. QB-002 uses whatever 2006-2014 picks for it. QB-001's probabilities come from
   the default code path, and a test checks them against the saved qb001-backup-flag-v1
   predictions.
