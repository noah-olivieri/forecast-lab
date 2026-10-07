"""Polymarket US public market data (keyless gateway).

Event payloads embed each market's best bid/ask quote, so NFL needs one paginated call and econ
needs one more; no per-market BBO calls. Limits of this source, recorded here on purpose:
  * no book sizes or open interest in the event payload (those columns are null);
  * quotes are as of the gateway's last sync, not necessarily this second (illiquid ladders
    can be stale), so treat Polymarket as a secondary, cross-venue reference.
YES is the market's `long` side. Tracked NFL markets: full-game winner, spread and total only
(props, halves and quarters are ~85% of the listing and out of scope).
"""

from __future__ import annotations

import re
from datetime import datetime

from lab.ingest.common import Api, to_float, to_ts

BASE_URL = "https://gateway.polymarket.us"
RPS = 5  # documented limit is 25/s; far below it
PAGE = 100

NFL_KIND = {
    "football_team_full_game_winner": "winner",
    "football_team_full_game_spread": "spread",
    "football_team_full_game_total": "total",
}
DEFAULT_ECON_TITLE_RE = (
    r"\b(CPI|Fed Decision|GDP Growth in Q\d|Jobs|Payrolls?|Unemployment|Jobless)\b"
)


def make_api(**kw) -> Api:
    return Api(BASE_URL, RPS, **kw)


def _paginate(api: Api, path: str, params: dict) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        data = api.get(path, {**params, "limit": PAGE, "offset": offset})
        batch = data.get("events", [])
        out.extend(batch)
        if len(batch) < PAGE:
            return out
        offset += PAGE


def fetch_nfl_events(api: Api) -> list[dict]:
    return _paginate(api, "/v2/leagues/nfl/events", {})


def fetch_macro_events(api: Api) -> list[dict]:
    return _paginate(
        api, "/v1/events", {"categories": "macro", "active": "true", "closed": "false"}
    )


def _quote(q) -> float | None:
    return to_float(q.get("value")) if isinstance(q, dict) else None


def _long_side(m: dict) -> str | None:
    for s in m.get("marketSides") or []:
        if s.get("long"):
            return s.get("description")
    return None


def normalize(m: dict, event: dict, *, group: str, kind: str, ts: datetime) -> dict:
    return {
        "venue": "polymarket_us",
        "ts_utc": ts,
        "market_ticker": m["slug"],
        "event_ticker": event.get("slug"),
        "series": "nfl" if group == "nfl" else "macro",
        "group": group,
        "kind": kind,
        "title": m.get("question") or m.get("title"),
        "subtitle": _long_side(m),
        "yes_bid": _quote(m.get("bestBidQuote")),
        "yes_ask": _quote(m.get("bestAskQuote")),
        "no_bid": None,
        "no_ask": None,
        "yes_bid_size": None,
        "yes_ask_size": None,
        "last": None,
        "volume": None,
        "volume_24h": None,
        "open_interest": None,
        "status": m.get("status"),
        "close_time": to_ts(m.get("endDate")),
        "event_time": to_ts(m.get("gameStartTime") or event.get("startTime"))
        if group == "nfl"
        else to_ts(event.get("endDate")),
        "strike_type": m.get("sportsMarketType") or m.get("marketType"),
        "floor_strike": to_float(m.get("line")),
        "cap_strike": None,
        "result": None,
    }


def snapshot(
    api: Api, ts: datetime, *, econ_title_re: str = DEFAULT_ECON_TITLE_RE
) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    errors: list[str] = []
    try:  # NFL first: it is the time-sensitive group
        for ev in fetch_nfl_events(api):
            for m in ev.get("markets") or []:
                kind = NFL_KIND.get(m.get("sportsMarketType"))
                if kind and m.get("active") and not m.get("closed"):
                    rows.append(normalize(m, ev, group="nfl", kind=kind, ts=ts))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"polymarket_us/nfl: {type(exc).__name__}: {exc}")
    try:
        pat = re.compile(econ_title_re, re.IGNORECASE)
        for ev in fetch_macro_events(api):
            if not pat.search(ev.get("title") or ""):
                continue
            for m in ev.get("markets") or []:
                if m.get("active") and not m.get("closed"):
                    rows.append(normalize(m, ev, group="econ", kind="econ", ts=ts))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"polymarket_us/econ: {type(exc).__name__}: {exc}")
    return rows, errors
