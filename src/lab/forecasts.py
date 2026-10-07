"""Forecast logger for NFL winner markets (PLAN 7a): build rows, then write one CSV in forecasts/.

p_yes is always P(home team wins). Kalshi's home-team market is used as-is; Polymarket US lists
a single market per game whose YES side may be the away team, so its quote is flipped and
swapped into the home team's perspective. `kickoff_ts` comes from config/kickoffs.json, never
from a venue's `event_time`. Nothing is written if any row's `created_ts` is not strictly before
its kickoff, and an existing file is never overwritten.

Columns differ from PLAN 7a in two ways: `kickoff_ts` replaces `event_close_ts`, and there is no
`forecast_id` (the DuckDB sequence assigns it when the batch is inserted after the push).
"""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import polars as pl

from lab.config import CONFIG_DIR, ROOT
from lab.features import nfl as nfl_features
from lab.ingest.nflverse import ET
from lab.models.baselines import market_mid
from lab.store.snapshots import list_hourly

MODEL_ELO = ("elo", "elo-538-default-v0")
MODEL_HOME = ("home_rate", "home-rate-v0")
MODEL_MID = ("market_mid", "market-mid-v0")
SNAPSHOT_TOLERANCE = timedelta(minutes=5)
KALSHI, POLYMARKET = "kalshi", "polymarket_us"

COLUMNS = [
    "model", "model_version", "git_sha", "venue", "market_ticker", "game_id", "yes_team",
    "prices_flipped", "as_of_ts", "p_yes", "created_ts", "kickoff_ts",
    "market_yes_bid", "market_yes_ask", "snapshot_ts",
]  # fmt: skip

# Kalshi uses JAC/LAR where nflverse uses JAX/LA.
_KALSHI_CODE = {"JAX": "JAC", "LA": "LAR"}
NICKNAMES = {
    "49ers": "SF", "Bears": "CHI", "Bengals": "CIN", "Bills": "BUF", "Broncos": "DEN",
    "Browns": "CLE", "Buccaneers": "TB", "Cardinals": "ARI", "Chargers": "LAC",
    "Chiefs": "KC", "Colts": "IND", "Commanders": "WAS", "Cowboys": "DAL",
    "Dolphins": "MIA", "Eagles": "PHI", "Falcons": "ATL", "Giants": "NYG",
    "Jaguars": "JAX", "Jets": "NYJ", "Lions": "DET", "Packers": "GB", "Panthers": "CAR",
    "Patriots": "NE", "Raiders": "LV", "Rams": "LA", "Ravens": "BAL", "Saints": "NO",
    "Seahawks": "SEA", "Steelers": "PIT", "Texans": "HOU", "Titans": "TEN", "Vikings": "MIN",
}  # fmt: skip


class ForecastError(ValueError):
    pass


class ForecastTooLate(ForecastError):
    """created_ts is not strictly before kickoff."""


def check_timing(created_ts: datetime, as_of_ts: datetime, kickoff_ts: datetime) -> None:
    for name, ts in (
        ("created_ts", created_ts),
        ("as_of_ts", as_of_ts),
        ("kickoff_ts", kickoff_ts),
    ):
        if ts.tzinfo is None:
            raise ForecastError(f"{name} must be timezone-aware")
    if created_ts >= kickoff_ts:
        raise ForecastTooLate(
            f"created_ts {created_ts:%FT%TZ} is not before kickoff {kickoff_ts:%FT%TZ}"
        )
    if created_ts < as_of_ts:
        raise ForecastError("created_ts is earlier than as_of_ts")


def flip_quote(bid: float | None, ask: float | None) -> tuple[float | None, float | None]:
    """YES quote of one side -> YES quote of the other: new bid = 1 - ask, new ask = 1 - bid."""
    new_bid = None if ask is None else round(1.0 - ask, 6)
    new_ask = None if bid is None else round(1.0 - bid, 6)
    return new_bid, new_ask


def load_kickoffs(path: Path = CONFIG_DIR / "kickoffs.json") -> dict[str, datetime]:
    games = json.loads(path.read_text())
    return {g["game_id"]: datetime.fromisoformat(g["kickoff_utc"]) for g in games}


def current_git_sha(repo: Path = ROOT, paths: tuple[str, ...] = ("src",)) -> str:
    """HEAD sha; refuses if code under `paths` has uncommitted or untracked changes."""
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    if dirty:
        raise ForecastError(f"uncommitted changes under {paths}; commit them so the SHA is true")
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def _latest_snapshot(data_root: Path, venue: str, cutoff: datetime) -> pl.DataFrame | None:
    """Newest hourly file whose rows were all captured at or before `cutoff`."""
    files = sorted(
        ((ts, p) for ts, v, p in list_hourly(data_root) if v == venue and ts <= cutoff),
        key=lambda x: x[0],
        reverse=True,
    )
    for _, path in files:
        df = pl.read_parquet(path)
        if df.height and df["ts_utc"].max() <= cutoff:
            return df
    return None


def _quote_row(df: pl.DataFrame | None, ticker: str) -> dict | None:
    if df is None:
        return None
    rows = df.filter(pl.col("market_ticker") == ticker).to_dicts()
    if len(rows) > 1:
        raise ForecastError(f"{len(rows)} rows for {ticker} in one snapshot")
    return rows[0] if rows else None


def _tickers(away: str, home: str, game_et: datetime) -> tuple[str, str]:
    ka, kh = _KALSHI_CODE.get(away, away), _KALSHI_CODE.get(home, home)
    kalshi = f"KXNFLGAME-{game_et:%y}{game_et:%b}{game_et:%d}".upper() + f"{ka}{kh}-{kh}"
    poly = f"aec-nfl-{away.lower()}-{home.lower()}-{game_et:%Y-%m-%d}"
    return kalshi, poly


def build_rows(
    con: duckdb.DuckDBPyConnection,
    data_root: Path,
    game_ids: list[str],
    as_of: datetime,
    created_ts: datetime,
    git_sha: str,
    kickoffs: dict[str, datetime],
) -> tuple[list[dict], list[str]]:
    """Rows for the home-team market of each game on each venue, plus warnings.

    `as_of` is an upper bound; each row's as_of_ts is the Kalshi snapshot's capture time, and
    the Polymarket quote must come from within SNAPSHOT_TOLERANCE of it (else it is skipped).
    """
    rows: list[dict] = []
    warnings: list[str] = []
    kalshi_df = _latest_snapshot(data_root, KALSHI, as_of)
    for game_id in game_ids:
        g = con.execute(
            "SELECT season, home_team, away_team, location FROM nfl_game WHERE game_id = ?",
            [game_id],
        ).fetchone()
        if g is None or game_id not in kickoffs:
            raise ForecastError(f"{game_id}: not in nfl_game and kickoffs.json")
        season, home, away, location = g
        kickoff = kickoffs[game_id]
        k_ticker, p_ticker = _tickers(away, home, kickoff.astimezone(ET))

        k_row = _quote_row(kalshi_df, k_ticker)
        if k_row is None:
            raise ForecastError(f"{game_id}: Kalshi market {k_ticker} not in snapshot")
        as_of_ts = k_row["ts_utc"]
        check_timing(created_ts, as_of_ts, kickoff)

        quotes = [(KALSHI, k_ticker, k_row, False)]
        p_cutoff = min(as_of_ts + SNAPSHOT_TOLERANCE, as_of)
        p_row = _quote_row(_latest_snapshot(data_root, POLYMARKET, p_cutoff), p_ticker)
        if p_row is None or abs(p_row["ts_utc"] - as_of_ts) > SNAPSHOT_TOLERANCE:
            warnings.append(f"{game_id}: no Polymarket US quote within {SNAPSHOT_TOLERANCE}")
        else:
            yes_team = NICKNAMES.get(p_row["subtitle"])
            if yes_team not in (home, away):
                raise ForecastError(f"{p_ticker}: cannot map YES side {p_row['subtitle']!r}")
            quotes.append((POLYMARKET, p_ticker, p_row, yes_team == away))

        neutral = location == "Neutral"
        p_elo = nfl_features.win_prob(con, home, away, as_of_ts, season, neutral)
        p_home = nfl_features.home_rate_baseline(con, as_of_ts, neutral)
        for venue, ticker, q, flipped in quotes:
            bid, ask = q["yes_bid"], q["yes_ask"]
            if flipped:
                bid, ask = flip_quote(bid, ask)
            base = {
                "git_sha": git_sha, "venue": venue, "market_ticker": ticker, "game_id": game_id,
                "yes_team": home, "prices_flipped": flipped, "as_of_ts": as_of_ts,
                "created_ts": created_ts, "kickoff_ts": kickoff, "market_yes_bid": bid,
                "market_yes_ask": ask, "snapshot_ts": q["ts_utc"],
            }  # fmt: skip
            mid = market_mid(bid, ask)
            for (model, version), p in ((MODEL_ELO, p_elo), (MODEL_HOME, p_home), (MODEL_MID, mid)):
                if p is not None:
                    rows.append({**base, "model": model, "model_version": version, "p_yes": p})
    return rows, warnings


def _fmt(v) -> str:
    if isinstance(v, datetime):
        return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return "" if v is None else str(v)


def write_batch(rows: list[dict], out_root: Path) -> Path:
    """Write `<out_root>/<game date ET>/nfl_<as_of>.csv`. Validates everything before writing."""
    if not rows:
        raise ForecastError("no rows to write")
    for r in rows:
        check_timing(r["created_ts"], r["as_of_ts"], r["kickoff_ts"])
    as_of = min(r["as_of_ts"] for r in rows)
    game_date = min(r["kickoff_ts"] for r in rows).astimezone(ET)
    path = out_root / f"{game_date:%Y-%m-%d}" / f"nfl_{as_of:%Y-%m-%dT%H-%MZ}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="") as f:  # "x": append-only, never overwrite
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in COLUMNS])
    return path
