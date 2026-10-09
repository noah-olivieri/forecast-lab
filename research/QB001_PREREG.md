# QB-001 pre-registration: Elo plus backup-QB flag (v1)

Date: 2026-10-09. Written and pushed before any QB-001 code or results exist.

Hypothesis: Frozen Elo ignores who starts at QB. Lowering a team's Elo when its usual
starter does not start will improve win-probability forecasts.

Data: pinned nfldata games.csv (commit 93a5221), starter IDs from home_qb_id and
away_qb_id. 4,853 of 4,861 games have both. Missing ID means no adjustment.

Usual starter: the QB with the most starts in the team's previous 8 games, counted across
seasons. Ties go to the most recent starter. No prior games means no adjustment.

My reasoning for this rule (my words): "I would say most starts in the last 8 weeks
because then even if there's a backup, it would still show the person who played the
majority of those games." The rule uses games, not weeks, so bye weeks don't matter.

Flag: tonight's starter is not the usual starter. Each team is checked on its own.

Adjustment: subtract the penalty from the flagged team's Elo for that game's probability
only. Rating updates stay exactly as frozen Elo.

Penalty: grid of 0 to 8 points of spread in 1-point steps, 25 Elo per point. Choose the
penalty with the lowest all-game Brier on 2006-2014 (ties y = 0.5). Ties between penalties
go to the smaller penalty.

Test: Elo+flag vs unchanged frozen Elo on 2015-2023. Paired Brier difference with the
registered paired block-bootstrap CI, on all games and on the decisive historical-moneyline
subset. Log loss reported as secondary. Success means the 95% CI excludes zero in Elo+flag's
favor. Anything else is a null result and is reported as one.

Also reported: flag rate (my guess: 20% of games), chosen penalty (my guess: 5 points),
and Elo+flag vs the moneyline reference on the decisive subset.

Limitations: the actual starter is known after the fact, which is mild lookahead at T-24h.
A new starter after an offseason change (rookie, trade or free agent) is flagged as a
backup until he leads the team's last 8 games in starts, usually his first 3 games. Report
the flag rate and Brier for weeks 1-4 separately as a diagnostic; this does not change the
success test. The 2015-2023 seasons were already viewed in RF-001, so this is development
evidence, not a final test.

## Clarifications

Added before the first push, before any QB-001 code or results exist.

1. Playoff games count toward a team's previous 8 games and are scored. This keeps the same
   game set as RF-001, whose 2,458 all-games count includes playoffs.
2. An earlier game with a missing QB ID is skipped when finding the usual starter. It does
   not count toward the 8 and gives no one a start. Only 8 games are affected, all in 2023.
3. With fewer than 8 earlier games, the rule uses whatever earlier games exist, if there is
   at least one. The prepared data starts in 2006, so early-2006 games have a shorter
   history. This affects only penalty selection, not the 2015-2023 test.
