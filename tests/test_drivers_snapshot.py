"""Pure logic of the NFL Drivers weekly snapshot (spec 2026-10-15). No network."""

import json
import shutil
import subprocess
from datetime import UTC, datetime
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
