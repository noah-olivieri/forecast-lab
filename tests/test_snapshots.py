from datetime import UTC, datetime, timedelta

import duckdb

from lab.store.snapshots import compact_completed_weeks, find_gaps, hourly_name, parse_hourly


def _write(root, ts, venue="kalshi", n=2):
    d = root / "snapshots/hourly"
    d.mkdir(parents=True, exist_ok=True)
    p = d / hourly_name(ts, venue)
    duckdb.connect().execute(
        f"COPY (SELECT '{ts.isoformat()}' AS ts_utc, range AS i FROM range({n})) "
        f"TO '{p.as_posix()}' (FORMAT parquet)"
    )
    return p


def test_name_roundtrip():
    ts = datetime(2026, 10, 12, 14, 5, tzinfo=UTC)
    assert parse_hourly(hourly_name(ts, "kalshi")) == (ts, "kalshi")
    assert parse_hourly("junk.parquet") is None


def test_no_data_is_not_a_gap(tmp_path):
    assert find_gaps(tmp_path, ["kalshi"], datetime(2026, 10, 12, 12, 0, tzinfo=UTC)) == {}


def test_detects_missing_hour_and_respects_grace(tmp_path):
    for h in (8, 9, 11):  # hour 10 is missing
        _write(tmp_path, datetime(2026, 10, 12, h, 5, tzinfo=UTC))
    now = datetime(2026, 10, 12, 12, 20, tzinfo=UTC)
    gaps = find_gaps(tmp_path, ["kalshi"], now, lookback_hours=None)
    assert gaps == {"kalshi": [datetime(2026, 10, 12, 10, 0, tzinfo=UTC)]}
    # hour 11 ended at 12:00; at 12:10 it is still inside the 15-minute grace window
    early = find_gaps(tmp_path, ["kalshi"], datetime(2026, 10, 12, 12, 10, tzinfo=UTC), lookback_hours=None)
    assert datetime(2026, 10, 12, 11, 0, tzinfo=UTC) not in early.get("kalshi", [])


def test_lookback_limits_old_gaps(tmp_path):
    for h in (1, 2, 20, 21, 22):  # gap 3..19 is old
        _write(tmp_path, datetime(2026, 10, 12, h, 5, tzinfo=UTC))
    now = datetime(2026, 10, 12, 23, 30, tzinfo=UTC)
    assert find_gaps(tmp_path, ["kalshi"], now, lookback_hours=3) == {}
    assert len(find_gaps(tmp_path, ["kalshi"], now, lookback_hours=None)["kalshi"]) == 17


def test_compaction_keeps_rows_and_only_finished_weeks(tmp_path):
    old = [datetime(2026, 10, 5, 0, 5, tzinfo=UTC) + timedelta(hours=i) for i in range(5)]  # ISO W41
    for ts in old:
        _write(tmp_path, ts, n=3)
    current = _write(tmp_path, datetime(2026, 10, 12, 9, 5, tzinfo=UTC))  # W42, unfinished
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)  # W41 ended 10-12 00:00; +6h settle passed
    res = compact_completed_weeks(tmp_path, now)
    assert len(res) == 1 and res[0].rows == 15 and len(res[0].removed) == 5
    assert current.exists()
    weekly = tmp_path / "snapshots/weekly/2026-W41_kalshi.parquet"
    assert duckdb.connect().execute(f"SELECT count(*) FROM read_parquet('{weekly}')").fetchone()[0] == 15
    assert compact_completed_weeks(tmp_path, now) == []  # idempotent


def test_compaction_waits_for_settle_window(tmp_path):
    _write(tmp_path, datetime(2026, 10, 5, 0, 5, tzinfo=UTC))
    assert compact_completed_weeks(tmp_path, datetime(2026, 10, 12, 3, 0, tzinfo=UTC)) == []
