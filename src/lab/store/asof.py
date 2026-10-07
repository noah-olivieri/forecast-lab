"""Point-in-time helpers. DuckDB timestamps in this project are naive UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def to_naive_utc(ts: datetime) -> datetime:
    """Aware datetime -> naive UTC for DuckDB. Naive input is refused, never guessed."""
    if ts.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return ts.astimezone(UTC).replace(tzinfo=None)
