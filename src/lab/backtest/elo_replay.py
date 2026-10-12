"""Single-pass replay of frozen Elo (elo-538-default-v0) for research backtests.

The old harness rebuilds each target game's history from scratch. Elo is sequential, so one
chronological pass gives every game's pre-game forecast. The frozen math in
`lab.models.nfl_elo` is called unchanged and in the same order as `lab.features.nfl`.

An optional hook takes (game, PreGame) and returns Elo adjustments (home, away) that are
subtracted from the ratings for that game's forecast only. Rating updates never see them,
as in QB-001. With no hook, the replay equals frozen Elo.

Only `reconstructed_scores` datasets are accepted: their history at any cutoff is a prefix
of one fixed, kickoff-ordered list. Under `strict_pit` a late label vintage can insert a game
into the middle of earlier history, so a single pass would not match.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from lab.backtest.score_data import FINISH_LAG, Dataset, Game, Observation, stamp
from lab.models import nfl_elo

MAX_SEASON = 2023  # 2024-2025 are the locked holdout; they never enter a replay
_END = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True)
class PreGame:
    """What a hook may see: state built only from games finished before `game.as_of`."""

    ratings: Mapping[str, float]  # pre-game ratings, regressed if this is a new season
    history: tuple[Observation, ...]  # eligible finished games, (kickoff, game_id) order


Hook = Callable[[Game, PreGame], tuple[float, float]]


def _targets(dataset):
    """`Dataset.targets()` for a reconstructed cohort, where the latest schedule is fixed."""
    latest = dataset.schedules_at(_END)
    found = {g.game_id: g for g in dataset.games if latest.get(g.game_id) == g}
    return sorted(found.values(), key=lambda g: (g.kickoff, g.game_id))


def _labels(dataset):
    """{game_id: label} with the same rule as `Dataset.evaluation_label`."""
    latest = {}
    for x in dataset.labels:
        if x.game_id not in latest or x.vintage.order(dataset.revision_clock) > latest[
            x.game_id
        ].vintage.order(dataset.revision_clock):
            latest[x.game_id] = x
    return {
        gid: x
        for gid, x in latest.items()
        if x.completed and x.home_score is not None and x.away_score is not None
    }


def replay(dataset: Dataset, hook: Hook | None = None, *, seasons=None) -> list[dict]:
    """One row per target game in (kickoff, game_id) order.

    `seasons` limits which targets get a row; earlier history is still replayed in full.
    """
    if dataset.cohort != "reconstructed_scores":
        raise ValueError("single-pass replay requires the reconstructed_scores cohort")
    # Filter the holdout out before anything is replayed.
    history = [o for o in dataset.eligible(_END) if o.game.season <= MAX_SEASON]
    targets = [g for g in _targets(dataset) if g.season <= MAX_SEASON]
    if seasons is not None:
        targets = [g for g in targets if g.season in seasons]
    labels = _labels(dataset)

    ratings: dict[str, float] = {}
    last_season = None
    i = 0
    rows = []
    for game in targets:
        # Same update order and regression points as lab.features.nfl.elo_ratings.
        while i < len(history) and history[i].game.kickoff + FINISH_LAG < game.as_of:
            o = history[i]
            if last_season is not None and o.game.season != last_season:
                ratings = nfl_elo.regress_to_mean(ratings)
            last_season = o.game.season
            hfa = 0.0 if o.game.location == "Neutral" else nfl_elo.HFA
            h = ratings.get(o.game.home_team, nfl_elo.INIT_ELO)
            a = ratings.get(o.game.away_team, nfl_elo.INIT_ELO)
            ratings[o.game.home_team], ratings[o.game.away_team] = nfl_elo.update(
                h, a, o.label.home_score, o.label.away_score, hfa
            )
            i += 1
        pre = ratings
        if last_season is not None and game.season > last_season:
            pre = nfl_elo.regress_to_mean(ratings)
        hfa = 0.0 if game.location == "Neutral" else nfl_elo.HFA
        elo_home = pre.get(game.home_team, nfl_elo.INIT_ELO)
        elo_away = pre.get(game.away_team, nfl_elo.INIT_ELO)
        adj_home = adj_away = 0.0
        if hook is not None:
            adj_home, adj_away = hook(
                game, PreGame(MappingProxyType(dict(pre)), tuple(history[:i]))
            )
        label = labels.get(game.game_id)
        y = None
        if label is not None:
            margin = label.home_score - label.away_score
            y = 1 if margin > 0 else 0 if margin < 0 else 0.5
        rows.append(
            {
                "game_id": game.game_id,
                "season": game.season,
                "week": game.week,
                "game_type": game.game_type,
                "kickoff": stamp(game.kickoff),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "elo_home": elo_home,
                "elo_away": elo_away,
                "p_elo": nfl_elo.expected_home(elo_home, elo_away, hfa),
                "adj_home": adj_home,
                "adj_away": adj_away,
                "p": nfl_elo.expected_home(elo_home - adj_home, elo_away - adj_away, hfa),
                "y": y,
            }
        )
    return rows


def qb001_hook(starters, points) -> Hook:
    """QB-001's backup-QB flag as a hook: `points` of spread off each flagged team's rating."""
    from lab.backtest.qb_flag import ELO_PER_POINT, backup_flags

    def hook(game, state):
        known = starters.get(game.game_id)
        if known and (known["home_team"], known["away_team"]) != (game.home_team, game.away_team):
            raise ValueError(f"starter source teams disagree: {game.game_id}")
        flags = backup_flags(game, state.history, starters)
        return (
            points * ELO_PER_POINT if flags["home"] else 0.0,
            points * ELO_PER_POINT if flags["away"] else 0.0,
        )

    return hook
