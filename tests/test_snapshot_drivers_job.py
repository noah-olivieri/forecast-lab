"""jobs/snapshot_drivers.py wiring, with the R export and quote capture faked. No network."""

import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab import drivers_snapshot as ds

JOB = Path(__file__).parent.parent / "jobs" / "snapshot_drivers.py"
spec = importlib.util.spec_from_file_location("snapshot_drivers", JOB)
sd = importlib.util.module_from_spec(spec)
sys.modules["snapshot_drivers"] = sd
spec.loader.exec_module(sd)

sys.path.insert(0, str(Path(__file__).parent))
from test_drivers_snapshot import fake_export, git, make_repo, quote, up_row

T = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def drivers_repo(tmp_path):
    repo = make_repo(tmp_path, "drivers")
    (repo / ".gitignore").write_text("data/cache/\n")
    (repo / "renv.lock").write_text('{"R": {"Version": "4.5.2"}}\n')
    git(repo, "add", ".gitignore", "renv.lock")
    git(repo, "commit", "-q", "-m", "ignore")
    cache = repo / "data" / "cache"
    cache.mkdir(parents=True)
    for name in ("results.rds", "schedules_2026.rds", "pbp_2026.rds"):
        (cache / name).write_bytes(name.encode())
    return repo


def fakes(tmp_path, drivers, *, quotes=None, created=None, features=False, code_sha=None,
          capture_at=T):  # fmt: skip
    """The fake export is stamped with the drivers repo's real HEAD unless told otherwise."""
    src = fake_export(tmp_path, [up_row()], features=features,
                      created=(created or T - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      code_sha=code_sha or git(drivers, "rev-parse", "HEAD"))  # fmt: skip

    def export_fn(results_rds, out_dir):
        assert results_rds.name == "results.rds"
        shutil.copytree(src, out_dir, dirs_exist_ok=True)

    def capture_fn():
        return quotes if quotes is not None else [], {"kalshi": [], "polymarket_us": []}, capture_at

    return export_fn, capture_fn


def run(tmp_path, config=None, slot_id=None, timing=None, **kw):
    drivers = drivers_repo(tmp_path)
    lab = make_repo(tmp_path, "lab")
    export_fn, capture_fn = fakes(tmp_path, drivers, **kw)
    return sd.take_snapshot(drivers, lab, lab / "drivers_snapshots", export_fn=export_fn,
                            capture_fn=capture_fn, config_kickoffs=config or {},
                            slot_id=slot_id, timing=timing)  # fmt: skip


def test_end_to_end_writes_snapshot_and_meta(tmp_path):
    q = [quote("kalshi", "KXNFLGAME-26OCT18HOUJAC-JAC", 0.66, 0.68)]
    d = run(tmp_path, quotes=q)
    assert d.parent.name == "2026-10-18" and d.name == "2026-10-18T12-00-00Z"
    meta = json.loads((d / "meta.json").read_text())
    assert meta["mode"] == "provenance_only" and meta["n_games"] == 1 and meta["n_excluded"] == 0
    assert meta["created_ts"] == "2026-10-18T12:00:00Z"
    assert meta["upcoming_dropped"] == 0
    assert len(meta["nfl_drivers_sha"]) == 40 and len(meta["forecast_lab_sha"]) == 40
    assert meta["sha256"]["schedules_2026.rds"] == ds.sha256_file(
        tmp_path / "drivers/data/cache/schedules_2026.rds"
    )
    assert (d / "inputs" / "schedules_2026.rds").exists()


def test_no_quotes_still_writes(tmp_path, capsys):
    d = run(tmp_path, quotes=[])
    assert (d / "predictions.csv").exists()
    assert "::error title=No quotes" in capsys.readouterr().out


def test_stale_results_refuse_and_write_nothing(tmp_path):
    with pytest.raises(ds.SnapshotRefused, match="more than"):
        run(tmp_path, created=T - timedelta(hours=7))
    assert not (tmp_path / "lab" / "drivers_snapshots").exists()


def test_dirty_drivers_repo_refuses(tmp_path):
    drivers = drivers_repo(tmp_path)
    (drivers / "R.R").write_text("x\n")
    lab = make_repo(tmp_path, "lab")
    export_fn, capture_fn = fakes(tmp_path, drivers)
    with pytest.raises(ds.SnapshotRefused, match="uncommitted"):
        sd.take_snapshot(drivers, lab, lab / "drivers_snapshots", export_fn=export_fn,
                         capture_fn=capture_fn, config_kickoffs={})  # fmt: skip


def test_main_returns_1_on_refusal(tmp_path, monkeypatch, capsys):
    def refuse(*a, **k):
        raise ds.SnapshotRefused("nope")

    monkeypatch.setattr(sd, "take_snapshot", refuse)
    assert sd.main(["--drivers", str(tmp_path)]) == 1
    assert "::error title=Snapshot refused::nope" in capsys.readouterr().out


def test_results_from_another_commit_refuse_and_write_nothing(tmp_path):
    with pytest.raises(ds.SnapshotRefused, match="came from nfl-drivers"):
        run(tmp_path, code_sha="0" * 40)
    assert not (tmp_path / "lab" / "drivers_snapshots").exists()


def test_kickoff_disagreement_reaches_meta_and_the_row(tmp_path):
    later = {"2026_06_HOU_JAX": datetime(2026, 10, 18, 14, 30, tzinfo=UTC)}
    d = run(tmp_path, config=later)
    meta = json.loads((d / "meta.json").read_text())
    assert [x["game_id"] for x in meta["kickoff_disagreements"]] == ["2026_06_HOU_JAX"]
    assert "kickoff_source_disagrees" in (d / "predictions.csv").read_text().splitlines()[0]
    assert (d / "predictions.csv").read_text().splitlines()[1].split(",")[6] == "True"



# ---- slot runs (spec 2026-10-19) --------------------------------------------------------------

KICK = datetime(2026, 10, 18, 13, 30, tzinfo=UTC)  # up_row()'s HOU@JAX, 09:30 ET
SLOT = "2026-10-18T13:30Z"  # t3 window [11:30Z, 12:45Z), grace to 13:30Z
CONFIG = {"2026_06_HOU_JAX": KICK}


def test_slot_run_labels_meta_and_rows(tmp_path):
    d = run(tmp_path, config=CONFIG, slot_id=SLOT, timing="t3")
    meta = json.loads((d / "meta.json").read_text())
    assert (meta["purpose"], meta["timing"], meta["slot"]) == ("main", "t3", SLOT)
    assert meta["sha256"]["renv.lock"] == ds.sha256_file(tmp_path / "drivers" / "renv.lock")
    assert "r_version" in meta and "r_packages" in meta
    header, row = (d / "predictions.csv").read_text().splitlines()[:2]
    assert header.endswith("purpose,timing,slot") and row.endswith(f"main,t3,{SLOT}")


def test_manual_run_is_main_without_slot(tmp_path):
    meta = json.loads((run(tmp_path) / "meta.json").read_text())
    assert (meta["purpose"], meta["timing"], meta["slot"]) == ("main", None, None)


def test_t3_written_after_close_within_grace(tmp_path):
    d = run(tmp_path, config=CONFIG, slot_id=SLOT, timing="t3",
            capture_at=datetime(2026, 10, 18, 12, 55, tzinfo=UTC))  # fmt: skip
    assert json.loads((d / "meta.json").read_text())["n_games"] == 1


def test_slot_run_refused_outside_window_plus_grace(tmp_path):
    with pytest.raises(ds.SnapshotRefused, match="opens"):
        run(tmp_path, config=CONFIG, slot_id=SLOT, timing="t3",
            capture_at=datetime(2026, 10, 18, 11, 29, tzinfo=UTC))  # fmt: skip
    assert not (tmp_path / "lab" / "drivers_snapshots").exists()


def test_unknown_slot_refused(tmp_path):
    with pytest.raises(ds.SnapshotRefused, match="no slot"):
        run(tmp_path, config=CONFIG, slot_id="2026-10-18T17:00Z", timing="t3")


def test_slot_and_timing_must_come_together():
    with pytest.raises(SystemExit) as e:
        sd.main(["--slot", SLOT])
    assert e.value.code == 2


def test_run_export_uses_drivers_cwd(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return sd.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(sd.subprocess, "run", fake_run)
    sd.run_export(tmp_path / "results.rds", tmp_path / "out", "Rscript", cwd=tmp_path / "drivers")
    assert seen["cwd"] == tmp_path / "drivers"
