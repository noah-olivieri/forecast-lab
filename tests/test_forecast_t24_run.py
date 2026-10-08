"""`run` subcommand of jobs/forecast_t24.py: builds and writes one CSV per game. No network:
the nflverse loader is injected and snapshots are tiny Parquet files in tmp dirs."""

import csv
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from lab.ingest.nflverse import game_rows
from lab.store.snapshots import hourly_name

JOB = Path(__file__).parent.parent / "jobs" / "forecast_t24.py"
spec = importlib.util.spec_from_file_location("forecast_t24", JOB)
ft = importlib.util.module_from_spec(spec)
sys.modules["forecast_t24"] = ft
spec.loader.exec_module(ft)

KICK = datetime(2026, 10, 9, 0, 15, tzinfo=UTC)  # TB@DAL, Thu 8:15 PM ET
NOW = KICK - timedelta(hours=23)  # inside [K-24h, K-21h)
SNAP = NOW - timedelta(minutes=4)
GO = datetime(2026, 10, 1, tzinfo=UTC)
GID, GID2 = "2026_05_TB_DAL", "2026_05_NYG_PHI"
K_TICKER = "KXNFLGAME-26OCT08TBDAL-DAL"
P_TICKER = "aec-nfl-tb-dal-2026-10-08"
ENV = {"GITHUB_RUN_ID": "99", "GITHUB_RUN_ATTEMPT": "2"}


@pytest.fixture(autouse=True)
def go_live(monkeypatch):
    monkeypatch.setattr(ft, "GO_LIVE", GO)


def snapshots(root, snap=SNAP):
    for venue, ticker, sub, bid, ask in (
        ("kalshi", K_TICKER, "Dallas", 0.79, 0.80),
        ("polymarket_us", P_TICKER, "Buccaneers", 0.2025, 0.205),
    ):
        df = pl.DataFrame({"ts_utc": [snap], "market_ticker": [ticker], "subtitle": [sub],
                           "yes_bid": [bid], "yes_ask": [ask]})  # fmt: skip
        d = root / "snapshots" / "hourly"
        d.mkdir(parents=True, exist_ok=True)
        df.write_parquet(d / hourly_name(snap, venue))


def nfl_games():
    def g(gid, season, day, time, home, away, hs, a_s):
        return {
            "game_id": gid, "season": season, "week": 1, "game_type": "REG", "gameday": day,
            "gametime": time, "away_team": away, "home_team": home, "away_score": a_s,
            "home_score": hs, "location": "Home",
        }  # fmt: skip

    return game_rows([
        g("2026_01_NYG_DAL", 2026, "2026-09-13", "13:00", "DAL", "NYG", 31, 17),
        g("2026_02_DAL_TB", 2026, "2026-09-20", "13:00", "TB", "DAL", 10, 20),
        g(GID, 2026, "2026-10-08", "20:15", "DAL", "TB", None, None),
        g(GID2, 2026, "2026-10-08", "20:15", "PHI", "NYG", None, None),
    ])  # fmt: skip


def setup(tmp_path, snap=SNAP, games=((GID, KICK),)):
    kick = tmp_path / "kickoffs.json"
    kick.write_text(json.dumps([
        {"game_id": g, "away": "A", "home": "H", "kickoff_utc": k.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for g, k in games
    ]))  # fmt: skip
    data = tmp_path / "data-branch"
    snapshots(data, snap)
    return kick, data, tmp_path / "forecasts"


def run(tmp_path, ids, now=NOW, snap=SNAP, games=((GID, KICK),), forecasts=None):
    kick, data, fdir = setup(tmp_path, snap, games)
    return ft.run_games(
        ids, now, kick, forecasts or fdir, data,
        load_games_fn=nfl_games, git_sha_fn=lambda: "abc123", env=ENV,
    )  # fmt: skip


def rows_of(path):
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))


FILE = "forecasts/2026-10-08/nfl-t24_2026_05_TB_DAL.csv"


def test_writes_one_file_per_game_with_provenance(tmp_path, monkeypatch, capsys):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert run(tmp_path, [GID]) == 0
    path = tmp_path / FILE
    rows = rows_of(path)
    assert {r["model"] for r in rows} == {"elo", "home_rate", "market_mid"}
    assert {r["venue"] for r in rows} == {"kalshi", "polymarket_us"}
    assert {(r["horizon"], r["run_id"], r["run_attempt"]) for r in rows} == {("t24", "99", "2")}
    assert {r["git_sha"] for r in rows} == {"abc123"}
    assert {r["created_ts"] for r in rows} == {NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert f"files={path}" in out.read_text().splitlines()
    assert f"written: {GID}" in capsys.readouterr().out


def test_writes_the_good_games_and_fails_the_rest(tmp_path, monkeypatch, capsys):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    code = run(tmp_path, [GID, GID2], games=((GID, KICK), (GID2, KICK)))
    printed = capsys.readouterr().out
    assert code == 1  # GID2 has no Kalshi market in the snapshot
    assert (tmp_path / FILE).exists()
    assert not list((tmp_path / "forecasts").rglob("*NYG_PHI*"))
    assert f"failed: {GID2}" in printed and "not in snapshot" in printed
    assert f"files={tmp_path / FILE}" in out.read_text().splitlines()


def test_existing_per_game_file_is_skipped_and_never_overwritten(tmp_path, capsys):
    path = tmp_path / FILE
    path.parent.mkdir(parents=True)
    path.write_text("model,game_id\nORIGINAL," + GID + "\n")
    assert run(tmp_path, [GID]) == 0
    assert path.read_text() == "model,game_id\nORIGINAL," + GID + "\n"
    assert f"skipped: {GID}" in capsys.readouterr().out


def test_game_in_a_legacy_batch_csv_is_skipped(tmp_path, capsys):
    legacy = tmp_path / "forecasts" / "2026-10-08" / "nfl_2026-10-08T00-05Z.csv"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(f"model,game_id\nelo,{GID}\n")
    assert run(tmp_path, [GID]) == 0
    assert not (tmp_path / FILE).exists()
    assert f"skipped: {GID}" in capsys.readouterr().out


def test_rechecks_existence_right_before_writing(tmp_path, monkeypatch, capsys):
    """Another run writes the file after our first check but before our write."""
    real = ft.forecast_game_ids
    path = tmp_path / FILE
    calls = []

    def fake(directory):
        calls.append(1)
        if len(calls) == 1:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("model,game_id\nOTHER_RUN," + GID + "\n")
            return set()
        return real(directory)

    monkeypatch.setattr(ft, "forecast_game_ids", fake)
    assert run(tmp_path, [GID]) == 0
    assert path.read_text() == "model,game_id\nOTHER_RUN," + GID + "\n"
    assert f"skipped: {GID}" in capsys.readouterr().out


def test_exclusive_create_is_the_last_line_of_defence(tmp_path, monkeypatch, capsys):
    """Even if both existence checks say no, the file is opened with "x" and never replaced."""
    path = tmp_path / FILE
    path.parent.mkdir(parents=True)
    path.write_text("model,game_id\nKEEP," + GID + "\n")
    monkeypatch.setattr(ft, "forecast_game_ids", lambda d: set())
    assert run(tmp_path, [GID]) == 0
    assert path.read_text() == "model,game_id\nKEEP," + GID + "\n"
    assert f"skipped: {GID}" in capsys.readouterr().out


def test_refuses_a_game_whose_window_is_not_open(tmp_path, capsys):
    """`run` re-derives the rule, so a hand-passed id outside the window is not forecast."""
    too_early = KICK - timedelta(hours=24, seconds=1)
    too_late = KICK - timedelta(hours=21)
    for now in (too_early, too_late):
        assert run(tmp_path, [GID], now=now) == 1
        assert f"failed: {GID}" in capsys.readouterr().out
    assert not (tmp_path / "forecasts").exists()


def test_refuses_a_game_before_go_live_plus_24h(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ft, "GO_LIVE", KICK - timedelta(hours=23))  # kickoff < GO_LIVE + 24h
    assert run(tmp_path, [GID]) == 1
    assert "not eligible" in capsys.readouterr().out
    assert not (tmp_path / "forecasts").exists()


def test_refuses_a_game_not_in_kickoffs_json(tmp_path, capsys):
    assert run(tmp_path, ["2026_99_XX_YY"]) == 1
    assert "not in kickoffs.json" in capsys.readouterr().out


def test_snapshot_older_than_30_minutes_fails_the_game(tmp_path, capsys):
    stale = NOW - ft.SNAPSHOT_MAX_AGE - timedelta(seconds=1)
    assert run(tmp_path, [GID], snap=stale) == 1
    printed = capsys.readouterr().out
    assert f"failed: {GID}" in printed and "old" in printed
    assert not (tmp_path / FILE).exists()


def test_snapshot_exactly_30_minutes_old_is_accepted(tmp_path):
    assert ft.SNAPSHOT_MAX_AGE == timedelta(minutes=30)
    assert run(tmp_path, [GID], snap=NOW - ft.SNAPSHOT_MAX_AGE) == 0
    assert (tmp_path / FILE).exists()


def test_run_with_no_games_is_a_no_op(tmp_path):
    assert run(tmp_path, []) == 0
    assert not (tmp_path / "forecasts").exists()
