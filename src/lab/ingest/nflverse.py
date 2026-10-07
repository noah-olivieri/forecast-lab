"""nflverse schedule/results -> `nfl_game`.

`gameday` + `gametime` are US/Eastern wall-clock; `kickoff_ts` is stored as naive UTC. Team codes
are canonicalised to the current franchise (OAK->LV, SD->LAC, STL->LA) so Elo ratings carry
across relocations. `nfl_game` is a mutable reference table (scores fill in after games);
forecasts and snapshots are the append-only data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import duckdb

ET = ZoneInfo("America/New_York")
FIRST_SEASON = 1999
FRANCHISE = {"OAK": "LV", "SD": "LAC", "STL": "LA"}


def kickoff_dt(gameday: str, gametime: str) -> datetime:
    """Aware-UTC kickoff from nflverse's Eastern gameday and gametime."""
    return datetime.fromisoformat(f"{gameday}T{gametime}").replace(tzinfo=ET).astimezone(UTC)


def to_kickoff_utc(gameday: str, gametime: str) -> str:
    return kickoff_dt(gameday, gametime).strftime("%Y-%m-%dT%H:%M:%SZ")


def _team(code: str) -> str:
    return FRANCHISE.get(code, code)


def game_rows(schedule: list[dict]) -> list[dict]:
    rows = []
    for r in schedule:
        has_time = r.get("gameday") and r.get("gametime")
        kickoff = kickoff_dt(r["gameday"], r["gametime"]).replace(tzinfo=None) if has_time else None
        rows.append(
            {
                "game_id": r["game_id"],
                "season": r["season"],
                "week": r["week"],
                "game_type": r["game_type"],
                "kickoff_ts": kickoff,
                "away_team": _team(r["away_team"]),
                "home_team": _team(r["home_team"]),
                "away_score": None if r.get("away_score") is None else int(r["away_score"]),
                "home_score": None if r.get("home_score") is None else int(r["home_score"]),
                "location": r.get("location"),
            }
        )
    return rows


def load_games(seasons: range | list[int] | None = None) -> list[dict]:
    import nflreadpy

    seasons = list(seasons or range(FIRST_SEASON, datetime.now(UTC).year + 1))
    return game_rows(nflreadpy.load_schedules(seasons).to_dicts())


def upsert_games(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> int:
    cols = list(rows[0])
    sql = (
        f"INSERT OR REPLACE INTO nfl_game ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    )
    con.executemany(sql, [[r[c] for c in cols] for r in rows])
    return len(rows)
