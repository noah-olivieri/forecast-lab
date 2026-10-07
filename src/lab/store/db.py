from __future__ import annotations

from pathlib import Path

import duckdb

from lab.config import DB_PATH

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: Path | str = DB_PATH) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SCHEMA_PATH.read_text())
