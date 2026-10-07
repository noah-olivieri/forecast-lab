from datetime import UTC, datetime

import httpx
import polars as pl
import pytest

from lab.ingest import kalshi, polymarket_us
from lab.ingest.common import SNAPSHOT_SCHEMA, Api, Throttle, to_float, write_snapshot

TS = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)


def _api(handler, base="https://example.test", rps=1000):
    return Api(base, rps, transport=httpx.MockTransport(handler))


def _k_market(ticker, **kw):
    m = {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "title": "Washington wins",
        "yes_sub_title": "Washington",
        "yes_bid_dollars": "0.2300",
        "yes_ask_dollars": "0.2400",
        "no_bid_dollars": "0.7600",
        "no_ask_dollars": "0.7700",
        "yes_bid_size_fp": "333.74",
        "yes_ask_size_fp": "3775.00",
        "last_price_dollars": "0.2400",
        "volume_fp": "207.46",
        "volume_24h_fp": "207.46",
        "open_interest_fp": "207.46",
        "status": "active",
        "close_time": "2026-10-22T00:15:00Z",
        "occurrence_datetime": "2026-10-20T03:15:00Z",
        "strike_type": "structured",
        "result": "",
    }
    m.update(kw)
    return m


def test_kalshi_pagination_and_normalize():
    pages = {
        "": {"markets": [_k_market("KXNFLGAME-A-X")], "cursor": "c1"},
        "c1": {"markets": [_k_market("KXNFLGAME-A-Y", floor_strike=3.5)], "cursor": ""},
    }
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=pages[req.url.params.get("cursor", "")])

    api = _api(handler)
    rows, errors = kalshi.snapshot(api, {"nfl": ["KXNFLGAME"]}, TS)
    assert errors == []
    assert [r["market_ticker"] for r in rows] == ["KXNFLGAME-A-X", "KXNFLGAME-A-Y"]
    assert seen[0]["series_ticker"] == "KXNFLGAME" and seen[0]["status"] == "open"
    r = rows[1]
    assert (r["kind"], r["group"], r["venue"]) == ("winner", "nfl", "kalshi")
    assert (r["yes_bid"], r["yes_ask"], r["yes_ask_size"]) == (0.23, 0.24, 3775.0)
    assert r["floor_strike"] == 3.5 and r["result"] is None
    assert r["event_time"] == datetime(2026, 10, 20, 3, 15, tzinfo=UTC)


def test_kalshi_nfl_processed_before_econ_and_failed_series_isolated():
    calls = []

    def handler(req):
        s = req.url.params["series_ticker"]
        calls.append(s)
        if s == "KXNFLSPREAD":
            return httpx.Response(400, json={})
        return httpx.Response(200, json={"markets": [_k_market(f"{s}-E-1")], "cursor": ""})

    rows, errors = kalshi.snapshot(
        _api(handler), {"nfl": ["KXNFLGAME", "KXNFLSPREAD"], "econ": ["KXCPI"]}, TS
    )
    assert calls == ["KXNFLGAME", "KXNFLSPREAD", "KXCPI"]
    assert {r["series"] for r in rows} == {"KXNFLGAME", "KXCPI"}
    assert len(errors) == 1 and "KXNFLSPREAD" in errors[0]
    assert {r["kind"] for r in rows} == {"winner", "econ"}


def test_retry_on_429_then_success(monkeypatch):
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda s: None)
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        if n["c"] < 3:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"ok": 1})

    assert _api(handler).get("/x") == {"ok": 1}
    assert n["c"] == 3


def test_no_retry_on_client_error(monkeypatch):
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda s: None)
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(404, json={})

    with pytest.raises(httpx.HTTPStatusError):
        _api(handler).get("/x")
    assert n["c"] == 1


def test_throttle_spaces_calls():
    t = Throttle(100)  # 10 ms apart
    import time

    start = time.monotonic()
    for _ in range(6):
        t.wait()
    assert time.monotonic() - start >= 0.045


def _pm_market(slug, kind, **kw):
    m = {
        "slug": slug,
        "question": "Will X?",
        "active": True,
        "closed": False,
        "status": "MARKET_STATUS_OPEN",
        "sportsMarketType": kind,
        "endDate": "2026-11-01T22:00:00Z",
        "gameStartTime": "2026-10-18T17:00:00Z",
        "bestBidQuote": {"value": "0.5300", "currency": "USD"},
        "bestAskQuote": {"value": "0.5375", "currency": "USD"},
        "marketSides": [
            {"description": "Bears", "long": True},
            {"description": "Falcons", "long": False},
        ],
    }
    m.update(kw)
    return m


def test_polymarket_filters_to_full_game_markets_and_econ_regex():
    nfl_event = {
        "slug": "nfl-chi-atl-2026-10-18",
        "markets": [
            _pm_market("aec-nfl-chi-atl-2026-10-18", "football_team_full_game_winner"),
            _pm_market("tsc-total-46pt5", "football_team_full_game_total", line=46.5),
            _pm_market("asc-1h", "football_team_first_half_spread"),  # out of scope
            _pm_market("asc-closed", "football_team_full_game_spread", closed=True),
            _pm_market("tsc-nobbo", "football_team_full_game_total", bestBidQuote=None),
        ],
    }
    macro = [
        {
            "slug": "uscpi-x",
            "title": "CPI MoM in September",
            "endDate": "2026-10-14T23:59:00Z",
            "markets": [_pm_market("cpi-1", "futures")],
        },
        {
            "slug": "boc",
            "title": "Bank of Canada Decision",
            "markets": [_pm_market("b", "futures")],
        },
    ]

    def handler(req):
        if req.url.path == "/v2/leagues/nfl/events":
            body = {"events": [nfl_event]}
        elif req.url.path == "/v1/events":
            assert req.url.params["categories"] == "macro"
            body = {"events": macro}
        else:
            return httpx.Response(404)
        return httpx.Response(200, json=body)

    rows, errors = polymarket_us.snapshot(_api(handler), TS)
    assert errors == []
    by = {r["market_ticker"]: r for r in rows}
    assert set(by) == {"aec-nfl-chi-atl-2026-10-18", "tsc-total-46pt5", "tsc-nobbo", "cpi-1"}
    w = by["aec-nfl-chi-atl-2026-10-18"]
    assert (w["kind"], w["subtitle"], w["yes_bid"], w["yes_ask"]) == (
        "winner",
        "Bears",
        0.53,
        0.5375,
    )
    assert w["event_time"] == datetime(2026, 10, 18, 17, 0, tzinfo=UTC)
    assert by["tsc-total-46pt5"]["floor_strike"] == 46.5
    assert by["tsc-nobbo"]["yes_bid"] is None  # empty book stays null, not 0
    assert by["cpi-1"]["group"] == "econ" and by["cpi-1"]["event_time"].day == 14


def test_polymarket_pagination():
    def handler(req):
        off = int(req.url.params["offset"])
        n = polymarket_us.PAGE if off == 0 else 3
        return httpx.Response(200, json={"events": [{"slug": f"e{off + i}"} for i in range(n)]})

    evs = polymarket_us.fetch_nfl_events(_api(handler))
    assert len(evs) == polymarket_us.PAGE + 3


def test_polymarket_nfl_failure_does_not_lose_econ():
    def handler(req):
        if req.url.path.startswith("/v2"):
            return httpx.Response(400)
        return httpx.Response(
            200,
            json={
                "events": [
                    {"slug": "u", "title": "CPI YoY", "markets": [_pm_market("c", "futures")]}
                ]
            },
        )

    rows, errors = polymarket_us.snapshot(_api(handler), TS)
    assert [r["market_ticker"] for r in rows] == ["c"]
    assert len(errors) == 1 and "nfl" in errors[0]


def test_write_snapshot_schema_roundtrip(tmp_path):
    rows, _ = kalshi.snapshot(
        _api(
            lambda r: httpx.Response(200, json={"markets": [_k_market("KXCPI-E-1")], "cursor": ""})
        ),
        {"econ": ["KXCPI"]},
        TS,
    )
    p = tmp_path / "snapshots/hourly/x.parquet"
    assert write_snapshot(rows, p) == 1
    df = pl.read_parquet(p)
    assert df.schema == pl.Schema(SNAPSHOT_SCHEMA)
    assert df["ts_utc"][0] == TS


def test_to_float_handles_junk():
    assert to_float("0.5") == 0.5 and to_float("") is None and to_float(None) is None
    assert to_float("n/a") is None


def _job():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "snapshot_markets", Path(__file__).parent.parent / "jobs" / "snapshot_markets.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(venue, ts):
    r = {c: None for c in SNAPSHOT_SCHEMA}
    r.update(
        venue=venue,
        ts_utc=ts,
        market_ticker="m",
        event_ticker="e",
        series="s",
        group="nfl",
        kind="winner",
    )
    return r


def test_job_writes_one_file_per_venue_and_survives_one_venue_failing(tmp_path, monkeypatch):
    job = _job()

    def fake_capture(venue, cfg, ts):
        if venue == "polymarket_us":
            raise RuntimeError("boom")
        return [_row(venue, ts)], []

    monkeypatch.setattr(job, "capture", fake_capture)
    assert job.main([str(tmp_path)]) == 0
    files = sorted(p.name for p in (tmp_path / "snapshots/hourly").glob("*.parquet"))
    assert len(files) == 1 and files[0].endswith("_kalshi.parquet")


def test_job_fails_when_nothing_captured_and_dry_run_writes_nothing(tmp_path, monkeypatch):
    job = _job()
    monkeypatch.setattr(job, "capture", lambda v, c, t: ([], ["down"]))
    assert job.main([str(tmp_path)]) == 1
    monkeypatch.setattr(job, "capture", lambda v, c, t: ([_row(v, t)], []))
    assert job.main([str(tmp_path), "--dry-run"]) == 0
    assert not (tmp_path / "snapshots").exists()
