import csv
import subprocess
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from lab import forecasts as fc
from lab.ingest.nflverse import game_rows, upsert_games
from lab.store.db import connect, init_schema
from lab.store.snapshots import hourly_name

KICK = datetime(2026, 10, 9, 0, 15, tzinfo=UTC)  # TB@DAL, Thu 8:15 PM ET
SNAP = datetime(2026, 10, 7, 2, 31, 49, tzinfo=UTC)
NOW = SNAP + timedelta(minutes=2)
K_TICKER = "KXNFLGAME-26OCT08TBDAL-DAL"
P_TICKER = "aec-nfl-tb-dal-2026-10-08"


def test_check_timing_rules():
    fc.check_timing(KICK - timedelta(seconds=1), SNAP, KICK)  # ok
    with pytest.raises(fc.ForecastTooLate):
        fc.check_timing(KICK, SNAP, KICK)  # equal is too late
    with pytest.raises(fc.ForecastTooLate):
        fc.check_timing(KICK + timedelta(minutes=1), SNAP, KICK)
    with pytest.raises(fc.ForecastError):
        fc.check_timing(SNAP - timedelta(seconds=1), SNAP, KICK)  # created before as_of
    with pytest.raises(fc.ForecastError):
        fc.check_timing(NOW.replace(tzinfo=None), SNAP, KICK)  # naive


def test_flip_quote_swaps_and_inverts():
    # Polymarket TB 0.2025 / 0.205  ->  DAL bid = 1 - TB ask, DAL ask = 1 - TB bid
    assert fc.flip_quote(0.2025, 0.205) == (pytest.approx(0.795), pytest.approx(0.7975))
    assert fc.flip_quote(None, 0.3) == (0.7, None)


def _snapshots(tmp_path):
    for venue, rows in {
        "kalshi": [(K_TICKER, "Dallas", 0.79, 0.80)],
        "polymarket_us": [(P_TICKER, "Buccaneers", 0.2025, 0.205)],
    }.items():
        df = pl.DataFrame(
            {
                "ts_utc": [SNAP] * len(rows),
                "market_ticker": [r[0] for r in rows],
                "subtitle": [r[1] for r in rows],
                "yes_bid": [r[2] for r in rows],
                "yes_ask": [r[3] for r in rows],
            }
        )
        d = tmp_path / "snapshots" / "hourly"
        d.mkdir(parents=True, exist_ok=True)
        df.write_parquet(d / hourly_name(SNAP, venue))


def _con():
    con = connect(":memory:")
    init_schema(con)

    def g(gid, season, day, time, home, away, hs, a_s):
        return {
            "game_id": gid, "season": season, "week": 1, "game_type": "REG", "gameday": day,
            "gametime": time, "away_team": away, "home_team": home, "away_score": a_s,
            "home_score": hs, "location": "Home",
        }  # fmt: skip

    schedule = [
        g("2026_01_NYG_DAL", 2026, "2026-09-13", "13:00", "DAL", "NYG", 31, 17),
        g("2026_02_DAL_TB", 2026, "2026-09-20", "13:00", "TB", "DAL", 10, 20),
        g("2026_05_TB_DAL", 2026, "2026-10-08", "20:15", "DAL", "TB", None, None),
    ]
    upsert_games(con, game_rows(schedule))
    return con


def _build(tmp_path, created_ts=NOW):
    _snapshots(tmp_path)
    return fc.build_rows(
        _con(), tmp_path, ["2026_05_TB_DAL"], NOW, created_ts, "abc123", {"2026_05_TB_DAL": KICK}
    )


def test_polymarket_tb_market_is_flipped_into_dal_perspective(tmp_path):
    rows, warnings = _build(tmp_path)
    assert warnings == []
    poly = [r for r in rows if r["venue"] == "polymarket_us"]
    kal = [r for r in rows if r["venue"] == "kalshi"]
    assert {r["model"] for r in poly} == {"elo", "home_rate", "market_mid"}
    assert all(r["yes_team"] == "DAL" and r["prices_flipped"] for r in poly)
    assert poly[0]["market_yes_bid"] == pytest.approx(1 - 0.205)
    assert poly[0]["market_yes_ask"] == pytest.approx(1 - 0.2025)
    mid = next(r for r in poly if r["model"] == "market_mid")
    assert mid["p_yes"] == pytest.approx((0.795 + 0.7975) / 2)
    assert all(not r["prices_flipped"] and r["market_yes_bid"] == 0.79 for r in kal)
    assert all(r["kickoff_ts"] == KICK and r["as_of_ts"] == SNAP for r in rows)
    # one model forecast shared by both venues; Elo model labelled v0
    elo = {r["venue"]: r for r in rows if r["model"] == "elo"}
    assert elo["kalshi"]["p_yes"] == elo["polymarket_us"]["p_yes"]
    assert elo["kalshi"]["model_version"] == "elo-538-default-v0"


def test_polymarket_quote_outside_tolerance_is_skipped_not_stale_filled(tmp_path):
    _snapshots(tmp_path)
    old = SNAP - timedelta(minutes=30)
    d = tmp_path / "snapshots" / "hourly"
    (d / hourly_name(SNAP, "polymarket_us")).rename(d / hourly_name(old, "polymarket_us"))
    pl.read_parquet(d / hourly_name(old, "polymarket_us")).with_columns(
        ts_utc=pl.lit(old)
    ).write_parquet(d / hourly_name(old, "polymarket_us"))
    rows, warnings = fc.build_rows(
        _con(), tmp_path, ["2026_05_TB_DAL"], NOW, NOW, "abc", {"2026_05_TB_DAL": KICK}
    )
    assert {r["venue"] for r in rows} == {"kalshi"} and len(warnings) == 1


def test_write_batch_writes_csv_and_is_append_only(tmp_path):
    rows, _ = _build(tmp_path)
    out = tmp_path / "forecasts"
    path = fc.write_batch(rows, out)
    assert path == out / "2026-10-08" / "nfl_2026-10-07T02-31Z.csv"
    got = list(csv.DictReader(path.open()))
    assert len(got) == len(rows) and list(got[0]) == fc.COLUMNS
    assert got[0]["kickoff_ts"] == "2026-10-09T00:15:00Z"
    with pytest.raises(FileExistsError):
        fc.write_batch(rows, out)


def test_write_refuses_and_writes_nothing_when_created_at_or_after_kickoff(tmp_path):
    rows, _ = _build(tmp_path)
    out = tmp_path / "forecasts"
    for created in (KICK, KICK + timedelta(hours=1)):
        late = [{**r, "created_ts": created} for r in rows]
        with pytest.raises(fc.ForecastTooLate):
            fc.write_batch(late, out)
    assert not out.exists()


def test_build_refuses_when_now_is_after_kickoff(tmp_path):
    _snapshots(tmp_path)
    with pytest.raises(fc.ForecastTooLate):
        fc.build_rows(
            _con(), tmp_path, ["2026_05_TB_DAL"], KICK + timedelta(hours=2),
            KICK + timedelta(hours=2), "abc", {"2026_05_TB_DAL": KICK},
        )  # fmt: skip


def _git(repo, *args):
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=True).stdout


def test_current_git_sha_refuses_dirty_src(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "notes.txt").write_text("n\n")
    _git(tmp_path, "add", "src/a.py", "notes.txt")
    _git(tmp_path, "commit", "-q", "-m", "init")
    head = _git(tmp_path, "rev-parse", "HEAD").strip()

    assert fc.current_git_sha(tmp_path) == head  # clean
    (tmp_path / "notes.txt").write_text("changed\n")
    assert fc.current_git_sha(tmp_path) == head  # dirty outside src/ is fine

    (tmp_path / "src" / "a.py").write_text("x = 2\n")
    with pytest.raises(fc.ForecastError, match="uncommitted"):
        fc.current_git_sha(tmp_path)  # modified tracked file under src/

    _git(tmp_path, "checkout", "--", "src/a.py")
    assert fc.current_git_sha(tmp_path) == head
    (tmp_path / "src" / "new.py").write_text("y = 1\n")
    with pytest.raises(fc.ForecastError, match="uncommitted"):
        fc.current_git_sha(tmp_path)  # untracked file under src/
