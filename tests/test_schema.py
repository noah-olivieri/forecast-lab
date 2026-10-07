import duckdb
import pytest

from lab.store.db import connect, init_schema


def test_schema_and_forecast_checks():
    con = connect(":memory:")
    init_schema(con)
    ins = (
        "INSERT INTO forecast (model, model_version, git_sha, venue, market_ticker,"
        " as_of_ts, p_yes, created_ts) VALUES ('m','v1','abc','kalshi','T', ?, ?, ?)"
    )
    con.execute(ins, ["2026-10-06 12:00:00", 0.4, "2026-10-06 12:00:01"])
    with pytest.raises(duckdb.ConstraintException):  # p out of range
        con.execute(ins, ["2026-10-06 12:00:00", 1.4, "2026-10-06 12:00:01"])
    with pytest.raises(duckdb.ConstraintException):  # created before as_of
        con.execute(ins, ["2026-10-06 12:00:05", 0.4, "2026-10-06 12:00:01"])
