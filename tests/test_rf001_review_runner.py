import json
from datetime import UTC, datetime

import pytest

from rf001_fixtures import label, module, schedule
from test_rf001_runner import manifest, runner


def test_writer_open_failure_records_owned_directory_only(tmp_path, monkeypatch):
    from pathlib import Path

    original = Path.open

    def denied(path, *args, **kwargs):
        if path.name == "events.jsonl":
            raise OSError("synthetic open fault")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(OSError):
        runner().RunWriter(tmp_path, "owned")
    assert json.loads((tmp_path / "owned/failure.json").read_text())["exception"] == "OSError"
    preserved = (tmp_path / "owned/failure.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner().RunWriter(tmp_path, "owned")
    assert (tmp_path / "owned/failure.json").read_bytes() == preserved


@pytest.mark.parametrize("stage", ["provenance", "targets", "splits", "interrupt"])
def test_created_runs_record_initialization_failures_and_interrupts(tmp_path, monkeypatch, stage):
    path = manifest(tmp_path / "input", [schedule()], [label()])
    rf = runner()
    exception = KeyboardInterrupt if stage == "interrupt" else RuntimeError

    def fail(*args, **kwargs):
        raise exception("deliberate synthetic fault")

    if stage in ("provenance", "interrupt"):
        monkeypatch.setattr(rf, "provenance", fail)
    elif stage == "targets":
        original = module("lab.backtest.score_data").Dataset.targets

        # Dataset construction already calls targets; only fail after directory creation.
        def targets(self):
            if (tmp_path / "runs" / "failed").exists():
                fail()
            return original(self)

        monkeypatch.setattr(module("lab.backtest.score_data").Dataset, "targets", targets)
    else:
        original = rf.RunWriter.json

        def write(self, name, value):
            if name == "splits.json":
                fail()
            return original(self, name, value)

        monkeypatch.setattr(rf.RunWriter, "json", write)
    with pytest.raises(exception):
        rf.run(path, tmp_path / "runs", "failed")
    assert json.loads((tmp_path / "runs/failed/failure.json").read_text()) == {
        "status": "failed",
        "exception": exception.__name__,
    }
    assert not (tmp_path / "runs/failed/manifest.json").exists()


def test_provenance_includes_alias_dependencies_and_transitive_baseline_source():
    value = runner().provenance()
    assert value["alias_version"] == module("lab.backtest.score_data").ALIAS_VERSION
    assert "src/lab/store/asof.py" in value["working_file_hashes"]
    assert "src/lab/backtest/score_artifacts.py" in value["working_file_hashes"]
    assert all(value["dependencies"][name] for name in ("numpy", "duckdb", "polars"))
    assert "blas" in value["numpy_build"]


def test_missing_kickoff_exclusion_stays_in_correct_slices_and_eligible_counts(tmp_path):
    kick = datetime(2015, 9, 1, tzinfo=UTC)
    path = runner().run(
        manifest(
            tmp_path / "input",
            [
                schedule("missing", kick, kickoff_ts_utc=None, week=2, location="Neutral"),
                schedule("miss", kick, home_team="OTHER", away_team="FOURTH"),
            ],
            [label("missing", kick), label("miss", kick)],
        ),
        tmp_path / "runs",
        "slices",
    )
    report = json.loads((path / "metrics.json").read_text())
    assert report["slices"]["rf001"]["early_regular"]["attempted"] == 2
    assert report["slices"]["rf001"]["early_regular"]["excluded"] == 1
    assert report["slices"]["rf001"]["neutral"]["excluded"] == 1
    compare = report["comparisons"]["half"]
    assert compare["eligible_candidate"] == 1
    assert compare["eligible_baseline"] == 1
    assert compare["scored_candidate"] == 0
    assert compare["scored_baseline"] == 1


def test_pit_histograms_keep_nonuniformity_hidden_by_equal_means():
    rf = runner()
    rows = [
        dict(
            game_id=str(i),
            model="rf001",
            role="outer",
            season=2015,
            week=1,
            game_type="REG",
            kickoff="2015-09-01T00:00:00Z",
            status="forecast",
            reason=None,
            p_share=0.5,
            y=1,
            brier=0.25,
            **{f"{name}_pit": value for name in ("home", "away", "margin", "total")},
        )
        for i, value in enumerate((0, 0, 1, 1))
    ]
    result = rf.metric_report(rows, rows, {}, synthetic=True)["outer"]["rf001"]
    assert result["margin_pit"] == 0.5
    assert result["margin_pit_histogram"] == [2, 0, 0, 0, 0, 0, 0, 0, 0, 2]


def test_real_run_seed_shopping_is_refused_before_creating_directory(tmp_path, monkeypatch):
    data = module("lab.backtest.score_data").Dataset.from_rows(
        [schedule()], [label()], "reconstructed_scores"
    )
    monkeypatch.setattr(
        runner(), "load_manifest", lambda _, **_options: (data, {"synthetic": False, "partitions": []})
    )
    with pytest.raises(ValueError, match="registered seed"):
        runner().run(tmp_path / "manifest.json", tmp_path / "runs", "seed", run_seed=123)
    assert not (tmp_path / "runs").exists()
