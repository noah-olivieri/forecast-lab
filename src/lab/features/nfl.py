"""NFL features. Every function takes `as_of` and sees only games that finished before it."""

from __future__ import annotations

from datetime import datetime, timedelta

import duckdb

from lab.models import nfl_elo
from lab.store.asof import to_naive_utc

# A game counts as finished this long after kickoff. Stricter than "kickoff < as_of": a game
# in progress or just ended is not yet known at as_of, even if its score is loaded later.
FINISH_LAG = timedelta(hours=4)


def finished_games(con: duckdb.DuckDBPyConnection, as_of: datetime) -> list[tuple]:
    """(season, home, away, home_score, away_score, location), kickoff-ordered."""
    cutoff = to_naive_utc(as_of) - FINISH_LAG
    return con.execute(
        """SELECT season, home_team, away_team, home_score, away_score, location
           FROM nfl_game
           WHERE kickoff_ts < ? AND home_score IS NOT NULL AND away_score IS NOT NULL
           ORDER BY kickoff_ts, game_id""",
        [cutoff],
    ).fetchall()


def elo_ratings(
    con: duckdb.DuckDBPyConnection, as_of: datetime, for_season: int
) -> dict[str, float]:
    """Ratings replayed from finished games, regressed if `for_season` is a new season."""
    ratings: dict[str, float] = {}
    last_season = None
    for season, home, away, hs, a_s, loc in finished_games(con, as_of):
        if last_season is not None and season != last_season:
            ratings = nfl_elo.regress_to_mean(ratings)
        last_season = season
        hfa = 0.0 if loc == "Neutral" else nfl_elo.HFA
        h = ratings.get(home, nfl_elo.INIT_ELO)
        a = ratings.get(away, nfl_elo.INIT_ELO)
        ratings[home], ratings[away] = nfl_elo.update(h, a, hs, a_s, hfa)
    if last_season is not None and for_season > last_season:
        ratings = nfl_elo.regress_to_mean(ratings)
    return ratings


def win_prob(
    con: duckdb.DuckDBPyConnection,
    home: str,
    away: str,
    as_of: datetime,
    season: int,
    neutral: bool = False,
) -> float:
    ratings = elo_ratings(con, as_of, season)
    hfa = 0.0 if neutral else nfl_elo.HFA
    return nfl_elo.expected_home(
        ratings.get(home, nfl_elo.INIT_ELO), ratings.get(away, nfl_elo.INIT_ELO), hfa
    )


def home_win_rate(con: duckdb.DuckDBPyConnection, as_of: datetime) -> float:
    """Flat home-team win rate over non-neutral finished games; ties count half."""
    wins = n = 0.0
    for _, _, _, hs, a_s, loc in finished_games(con, as_of):
        if loc == "Neutral":
            continue
        n += 1
        wins += 1.0 if hs > a_s else 0.5 if hs == a_s else 0.0
    if n == 0:
        raise ValueError("no finished games before as_of")
    return wins / n


def home_rate_baseline(con: duckdb.DuckDBPyConnection, as_of: datetime, neutral: bool) -> float:
    """Flat baseline P(home wins): the home rate, or 0.5 at a neutral site (no home team)."""
    return 0.5 if neutral else home_win_rate(con, as_of)
