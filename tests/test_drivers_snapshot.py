"""Pure logic of the NFL Drivers weekly snapshot (spec 2026-10-15). No network."""

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
                downloaded="2026-10-18T09:00:00Z", dropped=0, features=False):  # fmt: skip
    d = tmp_path / "export"
    d.mkdir(parents=True)
    lines = [",".join(UP_COLS)] + [",".join(r[c] for c in UP_COLS) for r in rows]
    (d / "upcoming.csv").write_text("\n".join(lines) + "\n")
    if features:
        (d / "features.csv").write_text("game_id,season,week,weather_imputed\nx,2026,6,0\n")
    meta = {"created": created, "schedule_downloaded": downloaded,
            "upcoming_dropped": dropped, "n_rows": len(rows)}  # fmt: skip
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
  upcoming_dropped = 1L, upcoming = up)
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
