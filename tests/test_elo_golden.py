"""Exact benchmark outputs captured before the unattended-forecast refactor."""

from datetime import UTC, datetime

import pytest

from lab.features import nfl as nfl_features
from lab.store.db import connect, init_schema


@pytest.fixture
def golden_games():
    con = connect(":memory:")
    init_schema(con)
    con.executemany(
        """INSERT INTO nfl_game
           (game_id, season, kickoff_ts, home_team, away_team,
            home_score, away_score, location) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("2025_01_TB_DAL", 2025, "2025-09-07 17:00", "DAL", "TB", 28, 10, "Home"),
            ("2025_02_DAL_NYG", 2025, "2025-09-14 17:00", "NYG", "DAL", 17, 17, "Home"),
            ("2025_03_NYG_TB", 2025, "2025-09-21 13:00", "TB", "NYG", 7, 24, "Neutral"),
            ("2026_01_TB_DAL", 2026, "2026-09-13 17:00", "DAL", "TB", 14, 21, "Home"),
            ("2026_02_DAL_NYG", 2026, "2026-09-20 17:00", "NYG", "DAL", None, None, "Home"),
        ],
    )
    yield con
    con.close()


@pytest.mark.parametrize(
    "home,away,as_of,season,neutral,elo,home_rate",
    [
        ("DAL", "TB", "2025-09-22T00:00:00+00:00", 2025, False, 0.6891504797784799, 0.75),
        ("DAL", "TB", "2026-09-13T21:00:00+00:00", 2026, False, 0.6582466657858116, 0.75),
        ("NYG", "DAL", "2026-09-20T16:00:00+00:00", 2026, True, 0.5446651301891642, 0.5),
    ],
)
def test_frozen_benchmark_outputs(golden_games, home, away, as_of, season, neutral, elo, home_rate):
    cutoff = datetime.fromisoformat(as_of).astimezone(UTC)
    assert nfl_features.win_prob(golden_games, home, away, cutoff, season, neutral) == elo
    assert nfl_features.home_rate_baseline(golden_games, cutoff, neutral) == home_rate
