import json

import numpy as np
import pytest

from rf001_fixtures import history, module


def test_training_records_share_prefixes_and_detect_tampering(tmp_path):
    data = module("lab.backtest.score_data")
    schedules, labels = history(110)
    ds = data.Dataset.from_rows(schedules, labels, "reconstructed_scores")
    artifacts = module("lab.backtest.score_artifacts")
    store = artifacts.RecordStore(tmp_path)
    prior = ds.eligible(ds.targets()[-1].as_of)
    sizes = {}
    for n in range(1, len(prior) + 1):
        store.observations(prior[:n])
        if n in (50, 100):
            sizes[n] = sum(p.stat().st_size for p in tmp_path.rglob("*.json"))
    assert sizes[100] / sizes[50] < 2.5  # full histories would grow about fourfold
    first = store.observations(prior[:-1])
    second = store.observations(prior)
    assert artifacts.read_observations(tmp_path, second) == prior
    assert artifacts.read_observations(tmp_path, first) == prior[:-1]
    assert len(list((tmp_path / "sequences").glob("*.json"))) == len(prior)
    node = json.loads((tmp_path / second).read_text())
    record = tmp_path / node["record"]
    changed = json.loads(record.read_text())
    changed["value"]["label"]["home_score"] = 99
    record.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="content hash"):
        artifacts.read_observations(tmp_path, second)


def test_saved_compact_forecast_can_be_independently_reconstructed(tmp_path):
    from test_rf001_runner import manifest, read_lines, runner

    schedules, labels = history(151)
    path = runner().run(manifest(tmp_path / "input", schedules, labels), tmp_path / "runs", "cas")
    row = next(
        r
        for r in read_lines(path / "predictions.jsonl")
        if r["game_id"] == "synthetic-0150" and r["model"] == "league"
    )
    audit = json.loads((path / row["fit_path"]).read_text())
    assert "training" not in audit
    assert "training_root" in audit
    assert (path / row["fit_path"]).stat().st_size < 2500
    artifacts = module("lab.backtest.score_artifacts")
    model = module("lab.models.nfl_score")
    restored = artifacts.read_observations(path, audit["training_root"])
    assert len(restored) == row["training_games"]
    target = artifacts.read_record(path, row["schedule_ref"])
    assert target["kind"] == "Game"
    assert module("lab.backtest.score_data").digest(target["value"]) == row["schedule_hash"]
    refit = model.fit_score(
        restored, module("lab.backtest.score_data").utc(row["as_of"]), league=True
    )
    assert refit.audit == audit
    bank = artifacts.read_bank(path, row["bank_path"])
    assert len(bank) == 50
    for item in bank:
        original = json.loads((path / item["fit_path"]).read_text())
        replay = model.fit_score(
            artifacts.read_observations(path, original["training_root"]),
            module("lab.backtest.score_data").utc(item["fit_as_of"]),
            league=True,
        )
        assert replay.audit == original
        mean_target = artifacts.read_record(path, item["fit_schedule_ref"])["value"]
        assert (
            list(
                replay.predict(
                    mean_target["home_team"],
                    mean_target["away_team"],
                    mean_target["location"] == "Neutral",
                )
            )
            == item["prior_means"]
        )
        stored_label = artifacts.read_record(path, item["label_ref"])["value"]
        assert item["residual"] == [
            stored_label["home_score"] - item["prior_means"][0],
            stored_label["away_score"] - item["prior_means"][1],
        ]
    draws = model.sample_scores(
        (row["fitted_home_mean"], row["fitted_away_mean"]),
        bank,
        row["game_id"],
        module("lab.backtest.score_data").utc(row["as_of"]),
        20261008,
        row["game_type"],
    )
    with np.load(path / row["samples_path"]) as archive:
        np.testing.assert_array_equal(draws.samples, archive["samples"])
    fallback = next(
        r
        for r in read_lines(path / "predictions.jsonl")
        if r["game_id"] == row["game_id"] and r["model"] == "rf001"
    )
    for field in ("samples_path", "bank_path", "probability_table_path"):
        assert fallback[field] == row[field]
    checks = json.loads((path / "metrics.json").read_text())["monte_carlo"]["checks"]
    assert len(checks) == 1
    assert checks[0]["models"] == ["rf001", "league"]
