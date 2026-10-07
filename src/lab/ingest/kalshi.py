"""Kalshi public market data (keyless). One paginated `/markets` call per series.

The `/markets` payload already carries best bid/ask and sizes, so no per-market order-book
calls are needed; that keeps a full run to a few dozen requests. Only open markets are listed;
settled markets drop out and are resolved by the settle job (M2).
"""

from __future__ import annotations

from datetime import datetime

from lab.ingest.common import Api, to_float, to_ts

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
RPS = 5  # basic tier allows ~20 reads/s; stay well under it

NFL_KIND = {"KXNFLGAME": "winner", "KXNFLSPREAD": "spread", "KXNFLTOTAL": "total"}


def make_api(**kw) -> Api:
    return Api(BASE_URL, RPS, **kw)


def fetch_series_markets(api: Api, series: str, status: str = "open") -> list[dict]:
    out: list[dict] = []
    cursor = ""
    while True:
        params = {"series_ticker": series, "status": status, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        data = api.get("/markets", params)
        out.extend(data.get("markets", []))
        cursor = data.get("cursor") or ""
        if not cursor:
            return out


def normalize(m: dict, *, series: str, group: str, ts: datetime) -> dict:
    return {
        "venue": "kalshi",
        "ts_utc": ts,
        "market_ticker": m["ticker"],
        "event_ticker": m.get("event_ticker"),
        "series": series,
        "group": group,
        "kind": NFL_KIND.get(series, "econ") if group == "nfl" else "econ",
        "title": m.get("title"),
        "subtitle": m.get("yes_sub_title"),
        "yes_bid": to_float(m.get("yes_bid_dollars")),
        "yes_ask": to_float(m.get("yes_ask_dollars")),
        "no_bid": to_float(m.get("no_bid_dollars")),
        "no_ask": to_float(m.get("no_ask_dollars")),
        "yes_bid_size": to_float(m.get("yes_bid_size_fp")),
        "yes_ask_size": to_float(m.get("yes_ask_size_fp")),
        "last": to_float(m.get("last_price_dollars")),
        "volume": to_float(m.get("volume_fp")),
        "volume_24h": to_float(m.get("volume_24h_fp")),
        "open_interest": to_float(m.get("open_interest_fp")),
        "status": m.get("status"),
        "close_time": to_ts(m.get("close_time")),
        "event_time": to_ts(m.get("occurrence_datetime") or m.get("expected_expiration_time")),
        "strike_type": m.get("strike_type"),
        "floor_strike": to_float(m.get("floor_strike")),
        "cap_strike": to_float(m.get("cap_strike")),
        "result": m.get("result") or None,
    }


def snapshot(
    api: Api, series_by_group: dict[str, list[str]], ts: datetime
) -> tuple[list[dict], list[str]]:
    """Groups are processed in dict order, so list `nfl` before `econ`. Returns (rows, errors)."""
    rows: list[dict] = []
    errors: list[str] = []
    for group, series_list in series_by_group.items():
        for series in series_list:
            try:
                markets = fetch_series_markets(api, series)
            except Exception as exc:  # noqa: BLE001 - one bad series must not lose the rest
                errors.append(f"kalshi/{series}: {type(exc).__name__}: {exc}")
                continue
            rows.extend(normalize(m, series=series, group=group, ts=ts) for m in markets)
    return rows, errors
