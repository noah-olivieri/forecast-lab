"""Pure logic of the NFL Drivers weekly snapshot (spec 2026-10-15). No network."""

import csv
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab import drivers_snapshot as ds

REPO = Path(__file__).parent.parent
EXPORT_R = REPO / "jobs" / "export_drivers.R"
UP_COLS = [
    "model", "game_id", "season", "week", "gameday", "gametime", "away_team", "home_team",
    "away_qb_name", "home_qb_name", "spread", "pred_margin", "pred_win",
]  # fmt: skip


def up_row(game_id="2026_06_HOU_JAX", gameday="2026-10-18", gametime="09:30", away="HOU",
           home="JAX", pred_win="0.68", model="full_qb_ridge", **kw):  # fmt: skip
    row = {
        "model": model, "game_id": game_id, "season": "2026", "week": "6", "gameday": gameday,
        "gametime": gametime, "away_team": away, "home_team": home,
        "away_qb_name": "C.J. Stroud", "home_qb_name": "Trevor Lawrence", "spread": "2.5",
        "pred_margin": "5.5", "pred_win": pred_win,
    }  # fmt: skip
    row.update(kw)
    return row


def fake_export(tmp_path, rows, *, created="2026-10-18T10:00:00Z",
                downloaded="2026-10-18T09:00:00Z", dropped=0, features=False,
                code_sha="abc123", code_dirty=False):  # fmt: skip
    d = tmp_path / "export"
    d.mkdir(parents=True)
    lines = [",".join(UP_COLS)] + [",".join(r[c] for c in UP_COLS) for r in rows]
    (d / "upcoming.csv").write_text("\n".join(lines) + "\n")
    if features:
        (d / "features.csv").write_text("game_id,season,week,weather_imputed\nx,2026,6,0\n")
    meta = {"created": created, "schedule_downloaded": downloaded,
            "upcoming_dropped": dropped, "n_rows": len(rows),
            "code_sha": code_sha, "code_dirty": code_dirty}  # fmt: skip
    (d / "meta.json").write_text(json.dumps(meta))
    return d


def test_read_export_keeps_full_qb_ridge_rows_and_parses_times(tmp_path):
    d = fake_export(tmp_path, [up_row(), up_row(model="base")])
    ex = ds.read_export(d)
    assert [r["model"] for r in ex.upcoming] == ["full_qb_ridge"]
    assert ex.results_created == datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    assert ex.schedule_downloaded == datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
    assert ex.upcoming_dropped == 0
    assert ex.mode == "provenance_only"


def test_read_export_full_mode_when_features_exist(tmp_path):
    assert ds.read_export(fake_export(tmp_path, [up_row()], features=True)).mode == "full"


def test_read_export_null_times_become_none(tmp_path):
    ex = ds.read_export(fake_export(tmp_path, [up_row()], downloaded=None))
    assert ex.schedule_downloaded is None


def test_read_export_refuses_without_model_rows(tmp_path):
    with pytest.raises(ds.SnapshotRefused, match="full_qb_ridge"):
        ds.read_export(fake_export(tmp_path, [up_row(model="base")]))


def test_read_export_refuses_incomplete_export(tmp_path):
    d = fake_export(tmp_path, [up_row()])
    (d / "meta.json").unlink()
    with pytest.raises(ds.SnapshotRefused, match="incomplete"):
        ds.read_export(d)


RSCRIPT = shutil.which("Rscript")
MAKE_RDS = """
args <- commandArgs(TRUE)
up <- data.frame(model = c("full_qb_ridge", "base"), game_id = "2026_06_HOU_JAX",
  season = 2026L, week = 6L, gameday = as.Date("2026-10-18"), gametime = "09:30",
  away_team = "HOU", home_team = "JAX", away_qb_name = c("C.J. Stroud", NA),
  home_qb_name = "Trevor Lawrence", spread = 2.5, pred_margin = 5.5, pred_win = c(0.68, 0.6))
r <- list(created = as.POSIXct("2026-10-18 10:00:00", tz = "UTC"),
  schedule_downloaded = as.POSIXct("2026-10-18 02:00:00", tz = "America/Los_Angeles"),
  upcoming_dropped = 1L, upcoming = up, code_sha = "abc123", code_dirty = FALSE)
if (args[2] == "full") r$upcoming_features <- data.frame(game_id = "2026_06_HOU_JAX",
  season = 2026L, week = 6L, home = 1, weather_imputed = 1)
saveRDS(r, args[1])
"""


@pytest.mark.skipif(RSCRIPT is None, reason="Rscript not installed")
@pytest.mark.parametrize("mode", ["provenance_only", "full"])
def test_real_r_export_round_trip(tmp_path, mode):
    rds, out = tmp_path / "results.rds", tmp_path / "out"
    subprocess.run([RSCRIPT, "-e", MAKE_RDS, str(rds), mode], check=True)
    subprocess.run([RSCRIPT, str(EXPORT_R), str(rds), str(out)], check=True)
    ex = ds.read_export(out)
    assert ex.mode == mode
    assert len(ex.upcoming) == 1 and ex.upcoming[0]["away_qb_name"] == "C.J. Stroud"
    assert ex.upcoming[0]["gameday"] == "2026-10-18" and ex.upcoming[0]["gametime"] == "09:30"
    assert float(ex.upcoming[0]["pred_win"]) == pytest.approx(0.68)
    assert ex.results_created == datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    assert ex.schedule_downloaded == datetime(2026, 10, 18, 9, 0, tzinfo=UTC)  # PDT -> UTC
    assert ex.upcoming_dropped == 1
    assert ex.code_sha == "abc123" and ex.code_dirty is False
    assert ex.r_version.startswith("R version") and "jsonlite" in ex.r_packages


@pytest.mark.skipif(RSCRIPT is None, reason="Rscript not installed")
def test_real_r_export_fails_on_missing_fields(tmp_path):
    rds = tmp_path / "bad.rds"
    subprocess.run([RSCRIPT, "-e", f"saveRDS(list(created = Sys.time()), '{rds}')"], check=True)
    r = subprocess.run([RSCRIPT, str(EXPORT_R), str(rds), str(tmp_path / "o")],
                       capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode != 0 and "upcoming" in r.stderr
T = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)  # capture time in tests: Sunday 08:00 ET


# Fixed commit dates: results_created in the fixtures (2026-10-18) must stay after HEAD's commit
# time however late the tests run.
GIT_ENV = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-01T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-10-01T00:00:00Z"}  # fmt: skip


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True, env=GIT_ENV).stdout.strip()  # fmt: skip


def make_repo(tmp_path, name="r"):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def test_clean_head_returns_sha_for_a_clean_repo(tmp_path):
    repo = make_repo(tmp_path)
    assert ds.clean_head(repo) == git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("dirty", ["modified", "untracked"])
def test_clean_head_refuses_dirty_repo(tmp_path, dirty):
    repo = make_repo(tmp_path)
    if dirty == "modified":
        (repo / "a.txt").write_text("b\n")  # first porcelain line starts with a space
    else:
        (repo / "new.py").write_text("x\n")
    with pytest.raises(ds.SnapshotRefused, match="uncommitted"):
        ds.clean_head(repo)


def test_clean_head_allows_untracked_snapshots_only(tmp_path):
    repo = make_repo(tmp_path)
    snap = repo / "drivers_snapshots" / "2026-10-15" / "x"
    snap.mkdir(parents=True)
    (snap / "predictions.csv").write_text("x\n")
    assert ds.clean_head(repo, allow_prefix="drivers_snapshots/")
    (repo / "a.txt").write_text("b\n")
    with pytest.raises(ds.SnapshotRefused, match="a.txt"):
        ds.clean_head(repo, allow_prefix="drivers_snapshots/")


def committed_snapshot(tmp_path):
    repo = make_repo(tmp_path)
    snap = repo / "drivers_snapshots" / "d"
    snap.mkdir(parents=True)
    (snap / "p.csv").write_text("x\n")
    git(repo, "add", "drivers_snapshots")
    git(repo, "commit", "-q", "-m", "snapshot")
    return repo


@pytest.mark.parametrize("change", ["modify", "delete"])
def test_clean_head_refuses_changes_to_tracked_snapshots(tmp_path, change):
    repo = committed_snapshot(tmp_path)
    path = repo / "drivers_snapshots" / "d" / "p.csv"
    path.write_text("y\n") if change == "modify" else path.unlink()
    with pytest.raises(ds.SnapshotRefused, match="p.csv"):
        ds.clean_head(repo, allow_prefix="drivers_snapshots/")


def test_clean_head_refuses_a_staged_rename_out_of_the_snapshots(tmp_path):
    repo = committed_snapshot(tmp_path)
    (repo / "src").mkdir()
    git(repo, "mv", "drivers_snapshots/d/p.csv", "src/evil.py")
    with pytest.raises(ds.SnapshotRefused, match="evil.py"):
        ds.clean_head(repo, allow_prefix="drivers_snapshots/")


def test_results_must_postdate_the_drivers_commit(tmp_path):
    commit_time = ds.head_commit_time(make_repo(tmp_path))
    ds.check_results_after_commit(commit_time, commit_time)
    with pytest.raises(ds.SnapshotRefused, match="before"):
        ds.check_results_after_commit(commit_time - timedelta(seconds=1), commit_time)
    with pytest.raises(ds.SnapshotRefused):
        ds.check_results_after_commit(None, commit_time)


def test_results_code_must_be_head_and_clean(tmp_path):
    ds.check_results_code(ds.read_export(fake_export(tmp_path, [up_row()])), "abc123")


@pytest.mark.parametrize("sha,dirty,match", [
    ("other", False, "other"), ("abc123", True, "uncommitted"),
    (None, False, "no code SHA"), ("abc123", None, "uncommitted"),
])  # fmt: skip
def test_results_code_refuses_other_dirty_or_unknown_code(tmp_path, sha, dirty, match):
    ex = ds.read_export(fake_export(tmp_path, [up_row()], code_sha=sha, code_dirty=dirty))
    with pytest.raises(ds.SnapshotRefused, match=match):
        ds.check_results_code(ex, "abc123")


def ex_with(tmp_path, created, downloaded):
    iso = lambda t: None if t is None else t.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ds.read_export(fake_export(tmp_path, [up_row()], created=iso(created),
                                      downloaded=iso(downloaded)))  # fmt: skip


def test_freshness_allows_exactly_six_hours(tmp_path):
    ds.check_freshness(ex_with(tmp_path, T - timedelta(hours=6), T - timedelta(hours=6)), T)


@pytest.mark.parametrize("which", ["created", "downloaded"])
def test_freshness_refuses_six_hours_and_a_second(tmp_path, which):
    old, ok = T - timedelta(hours=6, seconds=1), T - timedelta(hours=1)
    ex = ex_with(tmp_path, old if which == "created" else ok, old if which == "downloaded" else ok)
    with pytest.raises(ds.SnapshotRefused, match="more than"):
        ds.check_freshness(ex, T)


def test_freshness_refuses_timestamps_after_capture(tmp_path):
    with pytest.raises(ds.SnapshotRefused, match="after capture"):
        ds.check_freshness(ex_with(tmp_path, T + timedelta(seconds=1), T), T)


def test_freshness_refuses_missing_schedule_download_time(tmp_path):  # Review Focus 2
    with pytest.raises(ds.SnapshotRefused, match="schedule_downloaded is missing"):
        ds.check_freshness(ex_with(tmp_path, T, None), T)


def test_schedule_kickoffs_convert_eastern_to_utc_across_dst():  # Review Focus 5
    k = ds.schedule_kickoffs([
        up_row(),  # 2026-10-18 09:30 EDT
        up_row(game_id="2026_09_A_B", gameday="2026-11-01", gametime="13:00"),  # EST
    ])  # fmt: skip
    assert k["2026_06_HOU_JAX"] == datetime(2026, 10, 18, 13, 30, tzinfo=UTC)
    assert k["2026_09_A_B"] == datetime(2026, 11, 1, 18, 0, tzinfo=UTC)


@pytest.mark.parametrize("gameday,gametime", [("", "13:00"), ("2026-10-18", ""),
                                              ("2026-10-18", "1pm")])  # fmt: skip
def test_schedule_kickoffs_fail_on_missing_or_bad_time(gameday, gametime):
    rows = [up_row(), up_row(game_id="2026_06_X_Y", gameday=gameday, gametime=gametime)]
    with pytest.raises(ds.SnapshotRefused, match="2026_06_X_Y"):
        ds.schedule_kickoffs(rows)


def test_effective_kickoffs_take_the_earlier_and_record_disagreements():
    a, b = datetime(2026, 10, 18, 17, tzinfo=UTC), datetime(2026, 10, 18, 20, 25, tzinfo=UTC)
    eff, dis = ds.effective_kickoffs({"g1": a, "g2": b, "g3": a},
                                     {"g1": a, "g2": b - timedelta(hours=1)})  # fmt: skip
    assert eff == {"g1": a, "g2": b - timedelta(hours=1), "g3": a}
    assert dis == [{"game_id": "g2", "schedule": "2026-10-18T20:25:00Z",
                    "kickoffs_json": "2026-10-18T19:25:00Z"}]  # fmt: skip
def quote(venue, ticker, bid, ask, ts=T - timedelta(seconds=30), subtitle=None, size=None):
    return {"venue": venue, "market_ticker": ticker, "ts_utc": ts, "subtitle": subtitle,
            "yes_bid": bid, "yes_ask": ask, "yes_bid_size": size, "yes_ask_size": size}  # fmt: skip


K_HOU_JAX = "KXNFLGAME-26OCT18HOUJAC-JAC"  # Review Focus 3: JAX -> JAC on Kalshi
P_HOU_JAX = "aec-nfl-hou-jax-2026-10-18"


def rows_for(tmp_path, up, quotes, created=T, config=None):
    ex = ds.read_export(fake_export(tmp_path, up))
    k = ds.schedule_kickoffs(ex.upcoming)
    eff, _ = ds.effective_kickoffs(k, config or {})
    return ds.build_rows(ex, k, eff, quotes, created, "abc123")


def test_ok_row_with_both_venues_and_flipped_polymarket(tmp_path):
    q = [quote("kalshi", K_HOU_JAX, 0.66, 0.68, size=100.0),
         quote("polymarket_us", P_HOU_JAX, 0.30, 0.33, subtitle="Texans")]  # YES = away
    rows, excluded, warnings = rows_for(tmp_path, [up_row()], q)
    (r,) = rows
    assert excluded == [] and warnings == []
    assert r["status"] == "ok" and r["p_home"] == 0.68 and r["pred_margin"] == 5.5
    assert r["model"] == "full_qb_ridge" and r["model_version"] == "nfl-drivers@abc123"
    assert r["kalshi_ticker"] == K_HOU_JAX and r["kalshi_yes_bid"] == 0.66
    assert r["kalshi_bid_size"] == 100.0
    assert r["poly_flipped"] is True and r["poly_yes_team_raw"] == "Texans"
    assert (r["poly_yes_bid"], r["poly_yes_ask"]) == (0.67, 0.7)  # 1 - ask, 1 - bid
    assert r["home_qb_projected"] == "Trevor Lawrence" and r["away_qb_projected"] == "C.J. Stroud"
    assert r["kickoff_ts"] == datetime(2026, 10, 18, 13, 30, tzinfo=UTC)
    assert r["minutes_to_kickoff"] == 90
    assert r["game_day_et"] == "2026-10-18" and r["same_day"] is True


def test_statuses_without_kalshi_or_any_quote(tmp_path):
    poly = [quote("polymarket_us", P_HOU_JAX, 0.6, 0.7, subtitle="Jaguars")]
    (r,), _, _ = rows_for(tmp_path, [up_row()], poly)
    assert r["status"] == "no_kalshi_quote" and r["kalshi_yes_bid"] is None
    assert r["poly_flipped"] is False and r["poly_yes_bid"] == 0.6
    rows, _, _ = rows_for(tmp_path / "b", [up_row()], [])
    assert rows[0]["status"] == "no_quotes" and ds.no_quotes_at_all(rows)


def test_stale_or_future_quotes_are_missing(tmp_path):
    q = [quote("kalshi", K_HOU_JAX, 0.66, 0.68, ts=T - timedelta(minutes=5, seconds=1)),
         quote("polymarket_us", P_HOU_JAX, 0.6, 0.7, ts=T + timedelta(seconds=1),
               subtitle="Jaguars")]  # fmt: skip
    (r,), _, warnings = rows_for(tmp_path, [up_row()], q)
    assert r["status"] == "no_quotes" and len(warnings) == 2


def test_quote_exactly_five_minutes_old_is_used(tmp_path):
    q = [quote("kalshi", K_HOU_JAX, 0.66, 0.68, ts=T - timedelta(minutes=5))]
    (r,), _, _ = rows_for(tmp_path, [up_row()], q)
    assert r["status"] == "ok"


def test_duplicate_ticker_rows_are_missing_with_a_warning(tmp_path):  # Review Focus 4
    q = [quote("kalshi", K_HOU_JAX, 0.66, 0.68), quote("kalshi", K_HOU_JAX, 0.1, 0.2)]
    (r,), _, warnings = rows_for(tmp_path, [up_row()], q)
    assert r["status"] == "no_quotes" and "2 kalshi rows" in warnings[0]


def test_unmappable_polymarket_side_is_missing_with_a_warning(tmp_path):
    q = [quote("polymarket_us", P_HOU_JAX, 0.6, 0.7, subtitle="Draw")]
    (r,), _, warnings = rows_for(tmp_path, [up_row()], q)
    assert r["poly_yes_bid"] is None and any("Draw" in w for w in warnings)


def test_started_game_is_excluded_at_the_boundary(tmp_path):
    kickoff = datetime(2026, 10, 18, 13, 30, tzinfo=UTC)
    rows, excluded, _ = rows_for(tmp_path, [up_row()], [], created=kickoff)
    assert rows == [] and excluded == [
        {"game_id": "2026_06_HOU_JAX", "kickoff_ts": kickoff, "reason": "game_started"}
    ]


def test_earlier_config_kickoff_excludes_the_game(tmp_path):
    early = {"2026_06_HOU_JAX": T}  # kickoffs.json says it already started
    rows, excluded, _ = rows_for(tmp_path, [up_row()], [], config=early)
    assert rows == [] and excluded[0]["reason"] == "game_started"


def test_na_prediction_is_excluded(tmp_path):  # Review Focus 1
    rows, excluded, _ = rows_for(tmp_path, [up_row(pred_win="")], [])
    assert rows == [] and excluded[0]["reason"] == "no_prediction"


def test_same_day_is_judged_in_eastern_time(tmp_path):  # Review Focus 5
    # 03:59Z on Oct 18 is 23:59 ET on Oct 17: not the game's day.
    (r,), _, _ = rows_for(tmp_path, [up_row()], [], created=datetime(2026, 10, 18, 3, 59, tzinfo=UTC))
    assert r["same_day"] is False
    # 04:00Z is 00:00 ET Oct 18: same day, inside the London game's 00:00-09:30 ET window.
    (r,), _, _ = rows_for(tmp_path / "b", [up_row()], [],
                          created=datetime(2026, 10, 18, 4, 0, tzinfo=UTC))  # fmt: skip
    assert r["same_day"] is True


def test_rows_are_sorted_by_kickoff_and_cover_every_column(tmp_path):
    up = [up_row(game_id="2026_06_DAL_GB", away="DAL", home="GB", gametime="20:20"), up_row()]
    rows, _, _ = rows_for(tmp_path, up, [])
    assert [r["game_id"] for r in rows] == ["2026_06_HOU_JAX", "2026_06_DAL_GB"]
    assert set(rows[0]) == set(ds.PRED_COLUMNS)
def test_snapshot_dir_is_dated_in_eastern_time(tmp_path):
    late = datetime(2026, 10, 18, 3, 30, 5, tzinfo=UTC)  # 23:30 ET on Oct 17
    assert ds.snapshot_dir(tmp_path, late) == tmp_path / "2026-10-17" / "2026-10-18T03-30-05Z"


def write(tmp_path, features=False, created=T):
    ex = ds.read_export(fake_export(tmp_path, [up_row()], features=features))
    sched = tmp_path / "schedules_2026.rds"
    sched.write_bytes(b"rds-bytes")
    rows, excluded, _ = rows_for(tmp_path / "r", [up_row()], [])
    return ds.write_snapshot(tmp_path / "out", created, rows, excluded, {"mode": ex.mode}, ex, sched)


def test_write_snapshot_writes_every_file(tmp_path):
    d = write(tmp_path, features=True)
    assert sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()) == [
        "excluded.csv", "inputs/features.csv", "inputs/schedules_2026.rds",
        "inputs/upcoming.csv", "meta.json", "predictions.csv",
    ]  # fmt: skip
    with (d / "predictions.csv").open(newline="") as f:
        (row,) = list(csv.DictReader(f))
    assert list(row) == ds.PRED_COLUMNS
    assert row["kickoff_ts"] == "2026-10-18T13:30:00Z" and row["kalshi_yes_bid"] == ""
    assert (d / "inputs/schedules_2026.rds").read_bytes() == b"rds-bytes"
    assert json.loads((d / "meta.json").read_text()) == {"mode": "full"}


def test_write_snapshot_provenance_only_has_no_features(tmp_path):
    d = write(tmp_path)
    assert not (d / "inputs/features.csv").exists()


def test_write_snapshot_never_overwrites(tmp_path):
    d = write(tmp_path)
    before = (d / "predictions.csv").read_bytes()
    ex = ds.read_export(tmp_path / "export")
    with pytest.raises(ds.SnapshotRefused, match="already exists"):
        ds.write_snapshot(tmp_path / "out", T, [], [], {}, ex, None)
    assert (d / "predictions.csv").read_bytes() == before


def test_sha256_file(tmp_path):
    p = tmp_path / "x"
    p.write_bytes(b"abc")
    assert ds.sha256_file(p) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert ds.sha256_file(tmp_path / "missing") is None


def test_write_snapshot_unserializable_meta_writes_nothing(tmp_path):
    ex = ds.read_export(fake_export(tmp_path, [up_row()]))
    with pytest.raises(TypeError):
        ds.write_snapshot(tmp_path / "out", T, [], [], {"created_ts": T}, ex, None)
    assert not ds.snapshot_dir(tmp_path / "out", T).exists()


def test_write_snapshot_failure_after_mkdir_removes_the_directory(tmp_path, monkeypatch):
    ex = ds.read_export(fake_export(tmp_path, [up_row()]))

    def broken_copy(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ds.shutil, "copyfile", broken_copy)
    with pytest.raises(OSError, match="disk full"):
        ds.write_snapshot(tmp_path / "out", T, [], [], {}, ex, None)
    assert not ds.snapshot_dir(tmp_path / "out", T).exists()


def test_kickoff_source_disagrees_when_kickoffs_json_is_later(tmp_path):
    later = {"2026_06_HOU_JAX": datetime(2026, 10, 18, 14, 30, tzinfo=UTC)}  # schedule 13:30Z
    ex = ds.read_export(fake_export(tmp_path, [up_row()]))
    k = ds.schedule_kickoffs(ex.upcoming)
    eff, dis = ds.effective_kickoffs(k, later)
    disagree = {d["game_id"] for d in dis}
    (r,), _, _ = ds.build_rows(ex, k, eff, [], T, "abc123", disagree=disagree)
    assert r["kickoff_source_disagrees"] is True


def test_polymarket_slug_uses_lar_for_the_rams(tmp_path):  # final review #1
    up = [up_row(game_id="2026_06_ARI_LA", away="ARI", home="LA", gametime="16:05")]
    q = [quote("kalshi", "KXNFLGAME-26OCT18ARILAR-LAR", 0.7, 0.72),
         quote("polymarket_us", "aec-nfl-ari-lar-2026-10-18", 0.7, 0.73, subtitle="Rams")]
    (r,), _, warnings = rows_for(tmp_path, up, q)
    assert r["poly_ticker"] == "aec-nfl-ari-lar-2026-10-18" and r["poly_yes_bid"] == 0.7
    assert r["kalshi_yes_bid"] == 0.7 and warnings == []


def test_a_missing_quote_is_warned_not_silent(tmp_path):
    (r,), _, warnings = rows_for(tmp_path, [up_row()], [])
    assert r["status"] == "no_quotes"
    assert any("no kalshi quote" in w and K_HOU_JAX in w for w in warnings)
    assert any("no polymarket_us quote" in w and P_HOU_JAX in w for w in warnings)



# ---- slots and labels (spec 2026-10-19) -------------------------------------------------------


def test_pred_columns_end_with_labels():
    assert ds.PRED_COLUMNS[-3:] == ["purpose", "timing", "slot"]


def test_rows_carry_labels_and_default_to_main(tmp_path):
    (r,), _, _ = rows_for(tmp_path, [up_row()], [])
    assert (r["purpose"], r["timing"], r["slot"]) == ("main", None, None)
    ex = ds.read_export(fake_export(tmp_path / "b", [up_row()]))
    k = ds.schedule_kickoffs(ex.upcoming)
    labels = {"purpose": "timing", "timing": "t24", "slot": "2026-10-18T13:30Z"}
    (r,), _, _ = ds.build_rows(ex, k, k, [], T, "abc123", labels=labels)
    assert (r["purpose"], r["timing"], r["slot"]) == ("timing", "t24", "2026-10-18T13:30Z")


def test_build_rows_slot_filter_marks_other_slot_and_not_in_results(tmp_path):
    up = [up_row(), up_row(game_id="2026_06_DAL_GB", away="DAL", home="GB", gametime="20:20")]
    ex = ds.read_export(fake_export(tmp_path, up))
    k = ds.schedule_kickoffs(ex.upcoming)
    late = datetime(2026, 10, 18, 13, 30, tzinfo=UTC)
    rows, excluded, _ = ds.build_rows(
        ex, k, k, [], T, "abc123", slot_games=frozenset({"2026_06_HOU_JAX", "2026_06_X_Y"}),
        config_kickoffs={"2026_06_X_Y": late},
    )  # fmt: skip
    assert [r["game_id"] for r in rows] == ["2026_06_HOU_JAX"]
    assert excluded == [
        {"game_id": "2026_06_DAL_GB", "kickoff_ts": k["2026_06_DAL_GB"], "reason": "other_slot"},
        {"game_id": "2026_06_X_Y", "kickoff_ts": late, "reason": "not_in_results"},
    ]


def test_read_export_r_packages_optional(tmp_path):
    ex = ds.read_export(fake_export(tmp_path, [up_row()]))
    assert ex.r_version is None and ex.r_packages is None
    d = fake_export(tmp_path / "b", [up_row()])
    meta = json.loads((d / "meta.json").read_text())
    meta |= {"r_version": "R version 4.5.2 (2025-10-31)", "r_packages": {"jsonlite": "2.0.0"}}
    (d / "meta.json").write_text(json.dumps(meta))
    ex = ds.read_export(d)
    assert ex.r_version.startswith("R version") and ex.r_packages == {"jsonlite": "2.0.0"}
