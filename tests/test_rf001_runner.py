import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from rf001_fixtures import history, label, module, schedule


def runner():
    return module("lab.backtest.nfl_score")


def manifest(tmp_path, schedules, labels, *, reverse=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    parts = []
    for kind, rows in (("schedules", schedules), ("labels", labels)):
        for season in sorted({r["season"] for r in rows}):
            records = [r for r in rows if r["season"] == season]
            if reverse:
                records.reverse()
            path = tmp_path / f"{kind}-{season}.csv"
            with path.open("w") as handle:
                writer = csv.DictWriter(handle, fieldnames=records[0])
                writer.writeheader()
                writer.writerows(records)
            parts.append(
                {
                    "path": path.name,
                    "season": season,
                    "kind": kind,
                    "role": "development",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "synthetic": True,
                "cohort": "reconstructed_scores",
                "partitions": parts,
            }
        )
    )
    return path


def experiment():
    schedules, labels = history(156)
    for season in range(2012, 2017):
        for week in (1, 2):
            kick = datetime(season, 9, 1, 17, tzinfo=UTC) + timedelta(days=7 * (week - 1))
            gid = f"outer-{season}-{week}"
            schedules.append(schedule(gid, kick, week=week, home_team="T0", away_team="T1"))
            labels.append(label(gid, kick, home_score=24 + week, away_score=20))
    return schedules, labels


def test_engine_uses_only_earlier_fit_residuals_and_records_gates():
    schedules, labels = history(151)
    data = module("lab.backtest.score_data")
    ds = data.Dataset.from_rows(schedules, labels, "reconstructed_scores")
    engine = runner().ChronologicalEngine()
    outputs = []
    for game in ds.targets():
        outputs.append(engine.predict(game, ds.eligible(game.as_of), (1, None), 7))
    assert outputs[99]["status"] == "miss"
    assert outputs[100]["status"] == "miss"  # first mean, zero out-of-sample residuals
    assert outputs[149]["status"] == "miss"  # only 49 chronological residuals
    assert outputs[150]["status"] == "forecast"
    result = outputs[150]
    assert len(result["distribution"].bank) == 50
    assert result["fit"]["n_games"] == 150
    for item in result["distribution"].bank:
        assert item["game_id"] != schedules[150]["game_id"]
        assert item["fit_as_of"] < result["as_of"]
        assert item["label_revision"] == "l1"


def test_league_fallback_uses_its_own_residual_bank():
    schedules, labels = history(152)
    ds = module("lab.backtest.score_data").Dataset.from_rows(
        schedules, labels, "reconstructed_scores"
    )
    engine = runner().ChronologicalEngine()
    for game in ds.targets()[:-1]:
        engine.predict(game, ds.eligible(game.as_of), (1, None), 7)
    game = ds.targets()[-1]
    # Newly introduced candidate setting has no historical residual predictions.
    output = engine.predict(game, ds.eligible(game.as_of), (100, 365), 7)
    assert output["status"] == "fallback"
    assert output["actual_model"] == "league-score-v1"
    assert all(x["recipe"] == "league" for x in output["distribution"].bank)
    assert output["reason"] == "insufficient_candidate_residuals"


def test_saved_outputs_nested_selection_permutation_and_future_mutation(tmp_path):
    schedules, labels = experiment()
    first = runner().run(manifest(tmp_path / "a", schedules, labels), tmp_path / "runs", "first")
    shuffled = runner().run(
        manifest(tmp_path / "b", schedules, labels, reverse=True), tmp_path / "runs", "shuffled"
    )
    for name in ("predictions.jsonl", "splits.json", "trial_ledger.json"):
        assert (first / name).read_bytes() == (shuffled / name).read_bytes()
    altered = [dict(x, home_score=99, away_score=0) if x["season"] == 2016 else x for x in labels]
    future = runner().run(manifest(tmp_path / "c", schedules, altered), tmp_path / "runs", "future")
    earlier = lambda p: [x for x in read_lines(p / "predictions.jsonl") if x["season"] <= 2015]
    assert earlier(first) == earlier(future)
    ledger = json.loads((first / "trial_ledger.json").read_text())
    assert len([x for x in ledger if x["outer_season"] == 2015]) == 9
    assert all(int(year) < x["outer_season"] for x in ledger for year in x["by_year"])
    predictions = earlier(first)
    outer = [x for x in predictions if x["season"] == 2015 and x["model"] == "rf001"]
    assert len(outer) == 2
    assert all(x["status"] == "forecast" for x in outer)
    stored = outer[0]
    draws = np.load(first / stored["samples_path"])["samples"]
    assert len(draws) == 10000
    assert stored["p_home"] == np.mean(draws[:, 0] > draws[:, 1])
    assert stored["p_share"] == stored["p_home"] + 0.5 * stored["p_tie"]
    assert (
        stored["samples_hash"]
        == hashlib.sha256((first / stored["samples_path"]).read_bytes()).hexdigest()
    )
    report = json.loads((first / "metrics.json").read_text())
    assert report["synthetic"] is True and report["historical_accuracy_claim"] is False
    assert report["outer"]["rf001"]["predicted"] == 4
    assert report["market_mid"]["status"] == "unavailable_no_same_cutoff_quotes"
    assert report["comparisons"]["league"]["brier"]["n"] == 4
    assert report["comparisons"]["league"]["margin_crps"]["n"] == 4
    assert (first / "manifest.json").exists()
    assert (first / "events.jsonl").exists()
    assert json.loads((first / "manifest.json").read_text())["status"] == "complete"
    with pytest.raises(FileExistsError):
        runner().run(tmp_path / "a" / "manifest.json", tmp_path / "runs", "first")


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_no_prediction_and_missing_label_coverage_is_explicit(tmp_path):
    kick = datetime(2015, 9, 1, tzinfo=UTC)
    schedules = [schedule("no-history", kick), schedule("missing-time", kick, kickoff_ts_utc=None)]
    path = runner().run(
        manifest(tmp_path / "input", schedules, [label("no-history", kick)]),
        tmp_path / "runs",
        "empty",
    )
    report = json.loads((path / "metrics.json").read_text())["outer"]["rf001"]
    assert report["attempted"] == 2
    assert report["eligible"] == 1
    assert report["missed"] == 1
    assert report["excluded"] == 1
    assert report["brier_eligible_bounds"] == [0, 1]
    assert report["promotion_coverage_gate"] is False
    assert report["brier"] is None


def test_evaluation_label_is_read_only_after_prediction_is_written(tmp_path, monkeypatch):
    data = module("lab.backtest.score_data")
    original = data.Dataset.evaluation_label
    observed = []

    def guarded(self, gid):
        events = read_lines(tmp_path / "runs" / "ordered" / "events.jsonl")
        assert any(e["game_id"] == gid and e["event"] == "predictions_saved" for e in events)
        observed.append(gid)
        return original(self, gid)

    monkeypatch.setattr(data.Dataset, "evaluation_label", guarded)
    path = runner().run(
        manifest(tmp_path / "input", [schedule()], [label()]), tmp_path / "runs", "ordered"
    )
    assert observed == ["g1"]
    assert path.is_dir()


def test_cli_rejects_holdout_without_output_directory(tmp_path):
    import os
    import subprocess
    import sys

    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cohort": "strict_pit",
                "synthetic": True,
                "partitions": [
                    {
                        "path": "unread.csv",
                        "season": 2024,
                        "role": "development",
                        "kind": "labels",
                        "sha256": "a" * 64,
                    }
                ],
            }
        )
    )
    command = [
        sys.executable,
        "-m",
        "lab.backtest.nfl_score",
        "--manifest",
        str(path),
        "--run-id",
        "forbidden-synthetic-holdout",
    ]
    # No sockets or network used; subprocess is the real offline entry point.
    result = subprocess.run(
        command,
        env=dict(os.environ, PYTHON_DOTENV_DISABLED="1"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "locked holdout" in result.stderr
    assert not Path("data/research/runs/forbidden-synthetic-holdout").exists()


def test_all_residual_fit_artifacts_exist_and_final_labels_are_auditable(tmp_path):
    schedules, labels = history(151)
    path = runner().run(manifest(tmp_path / "input", schedules, labels), tmp_path / "runs", "audit")
    rows = read_lines(path / "predictions.jsonl")
    league = next(r for r in rows if r["game_id"] == "synthetic-0150" and r["model"] == "league")
    bank = module("lab.backtest.score_artifacts").read_bank(path, league["bank_path"])
    assert len(bank) == 50
    assert all("fit_path" in item for item in bank)
    assert all((path / item["fit_path"]).exists() for item in bank)
    mean_only = next(r for r in rows if r["game_id"] == "synthetic-0100" and r["model"] == "league")
    assert mean_only["fitted_home_mean"] > 0
    assert (path / mean_only["mean_fit_path"]).exists()
    scored = json.loads((path / "evaluation.json").read_text())
    assert scored[0]["evaluation_label"]["home_score"] == 20
    assert scored[0]["evaluation_label"]["vintage"]["source_hash"] == "b" * 64


def test_revised_residuals_use_original_mean_and_current_eligible_label():
    schedules, labels = history(152)
    data = module("lab.backtest.score_data")
    ds = data.Dataset.from_rows(schedules, labels, "strict_pit")
    engine = runner().ChronologicalEngine()
    for game in ds.targets()[:-1]:
        engine.predict(game, ds.eligible(game.as_of), (1, None), 7)
    game = ds.targets()[-1]
    original_label = labels[100]
    corrected = dict(
        original_label,
        revision_id="correction",
        home_score=40,
        published_ts=(game.as_of - timedelta(hours=2)).isoformat(),
        fetched_ts=(game.as_of - timedelta(hours=1)).isoformat(),
    )
    revised = data.Dataset.from_rows(schedules, [*labels, corrected], "strict_pit")
    result = engine.predict(game, revised.eligible(game.as_of), (1, None), 7)
    residual = next(r for r in result["distribution"].bank if r["game_id"] == "synthetic-0100")
    assert residual["label_revision"] == "correction"
    assert residual["residual"][0] == 40 - residual["prior_means"][0]
    assert residual["fit_as_of"] == data.stamp(ds.targets()[100].as_of)


def test_model_prediction_engine_rejects_multiple_versions_and_invalid_target_type():
    schedules, labels = history(2)
    ds = module("lab.backtest.score_data").Dataset.from_rows(
        schedules, labels, "reconstructed_scores"
    )
    target = ds.targets()[-1]
    prior = ds.eligible(target.as_of)
    engine = runner().ChronologicalEngine()
    with pytest.raises(ValueError, match="duplicate"):
        engine.predict(target, prior * 2, (1, None), 7)
    with pytest.raises(TypeError, match="score-free"):
        engine.predict(dict(schedules[-1], home_score=99), prior, (1, None), 7)


def test_frozen_comparators_and_baseline_warmup_are_replayed_without_retuning():
    kick = datetime(2005, 9, 1, 17, tzinfo=UTC)
    target_time = datetime(2006, 9, 1, 17, tzinfo=UTC)
    data = module("lab.backtest.score_data")
    ds = data.Dataset.from_rows(
        [schedule("old", kick), schedule("next", target_time)],
        [label("old", kick, home_score=30, away_score=10)],
        "reconstructed_scores",
    )
    game = ds.targets()[-1]
    prior = ds.eligible(game.as_of)
    result = runner().frozen_predictions(prior, game)
    # Independent hand calculation of the frozen 538 recipe for one 20-point win
    # followed by 1/3 offseason regression, then the fixed 65-point home edge.
    import math

    p = 1 / (1 + 10 ** (-65 / 400))
    delta = 20 * math.log(21) * 2.2 / (2.2 + 0.065) * (1 - p)
    difference = (2 * delta) * 2 / 3
    expected = 1 / (1 + 10 ** (-(difference + 65) / 400))
    assert result["elo"] == pytest.approx(expected)
    assert result["home_rate"] == 1
    assert result["half"] == 0.5
    assert runner().ChronologicalEngine().predict(game, prior, (1, None), 7)["status"] == "miss"


def test_missing_final_labels_block_coverage_promotion_and_keep_bounds():
    row = {
        "game_id": "unknown",
        "model": "rf001",
        "season": 2015,
        "role": "outer",
        "status": "forecast",
        "reason": None,
        "p_share": 0.7,
    }
    report = runner().metric_report([row], [], {}, synthetic=True)["outer"]["rf001"]
    assert report["unlabelled"] == 1
    assert report["promotion_coverage_gate"] is False
    assert report["brier_eligible_bounds"] == [0, 1]


def test_rest_slice_metadata_matches_across_frozen_and_score_models(tmp_path):
    kick = datetime(2015, 9, 1, 17, tzinfo=UTC)
    later = kick + timedelta(days=7)
    schedules = [schedule("first", kick), schedule("second", later, week=2)]
    labels = [label("first", kick), label("second", later)]
    path = runner().run(manifest(tmp_path / "input", schedules, labels), tmp_path / "runs", "rest")
    second = [
        r
        for r in read_lines(path / "predictions.jsonl")
        if r["game_id"] == "second" and r["model"] in runner().MODELS
    ]
    assert len(second) == 5
    assert all(r.get("short_rest") is False for r in second)
    assert all(r.get("rest_days") == [7.0, 7.0] for r in second)
