"""Shared pieces for market snapshotters: throttled HTTP client, retries, snapshot schema/IO."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

USER_AGENT = "forecast-lab/0.1 (paper-trading research; github.com/noah-olivieri/forecast-lab)"

# One row per market per capture. Prices are dollars in [0, 1] for the YES side, exactly as the
# venue reported them (a bid of 0 with size 0 means an empty book, not a real 0c bid).
SNAPSHOT_SCHEMA: dict[str, pl.DataType] = {
    "venue": pl.String,
    "ts_utc": pl.Datetime("us", "UTC"),
    "market_ticker": pl.String,
    "event_ticker": pl.String,
    "series": pl.String,
    "group": pl.String,  # nfl | econ
    "kind": pl.String,  # winner | spread | total | econ
    "title": pl.String,
    "subtitle": pl.String,
    "yes_bid": pl.Float64,
    "yes_ask": pl.Float64,
    "no_bid": pl.Float64,
    "no_ask": pl.Float64,
    "yes_bid_size": pl.Float64,
    "yes_ask_size": pl.Float64,
    "last": pl.Float64,
    "volume": pl.Float64,
    "volume_24h": pl.Float64,
    "open_interest": pl.Float64,
    "status": pl.String,
    "close_time": pl.Datetime("us", "UTC"),
    # Venue-reported event time. Polymarket NFL: true kickoff (gameStartTime). Kalshi NFL:
    # occurrence_datetime, which is the expected game END (~3h after kickoff), not kickoff.
    # Econ: release/decision time as the venue reports it. Use nflverse for authoritative kickoff.
    "event_time": pl.Datetime("us", "UTC"),
    "strike_type": pl.String,
    "floor_strike": pl.Float64,
    "cap_strike": pl.Float64,
    "result": pl.String,
}


def to_float(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def to_ts(x) -> datetime | None:
    if not x:
        return None
    try:
        return datetime.fromisoformat(str(x)).astimezone(UTC)
    except ValueError:
        return None


class Throttle:
    """Spaces calls at least 1/rps seconds apart (thread-safe, not bursty)."""

    def __init__(self, rps: float):
        self.interval = 1.0 / rps
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class Api:
    """GET-only JSON client: client-side rate limit plus backoff on 429/5xx/network errors."""

    def __init__(self, base_url: str, rps: float, *, transport: httpx.BaseTransport | None = None):
        self.throttle = Throttle(rps)
        self.client = httpx.Client(
            base_url=base_url,
            timeout=20,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )

    @retry(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        reraise=True,
    )
    def get(self, path: str, params: dict | None = None) -> dict:
        self.throttle.wait()
        r = self.client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self.client.close()


def rows_to_frame(rows: Sequence[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SNAPSHOT_SCHEMA)


def write_snapshot(rows: Sequence[dict], path: Path) -> int:
    """Write rows as zstd Parquet; returns the row count. Sorted so repeated strings compress."""
    df = rows_to_frame(rows).sort(["group", "kind", "event_ticker", "market_ticker"])
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression="zstd", compression_level=9, statistics=False)
    return df.height
