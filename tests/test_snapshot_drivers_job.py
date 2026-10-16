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
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore")
    cache = repo / "data" / "cache"
    cache.mkdir(parents=True)
    for name in ("results.rds", "schedules_2026.rds", "pbp_2026.rds"):
        (cache / name).write_bytes(name.encode())
    return repo


def fakes(tmp_path, drivers, *, quotes=None, created=None, features=False, code_sha=None):
    """The fake export is stamped with the drivers repo's real HEAD unless told otherwise."""
    src = fake_export(tmp_path, [up_row()], features=features,
                      created=(created or T - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      code_sha=code_sha or git(drivers, "rev-parse", "HEAD"))  # fmt: skip

    def export_fn(results_rds, out_dir):
        assert results_rds.name == "results.rds"
        shutil.copytree(src, out_dir, dirs_exist_ok=True)

    def capture_fn():
        return quotes if quotes is not None else [], {"kalshi": [], "polymarket_us": []}, T

    return export_fn, capture_fn


def run(tmp_path, config=None, **kw):
    drivers = drivers_repo(tmp_path)
    lab = make_repo(tmp_path, "lab")
    export_fn, capture_fn = fakes(tmp_path, drivers, **kw)
    return sd.take_snapshot(drivers, lab, lab / "drivers_snapshots", export_fn=export_fn,
                            capture_fn=capture_fn, config_kickoffs=config or {})  # fmt: skip


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

