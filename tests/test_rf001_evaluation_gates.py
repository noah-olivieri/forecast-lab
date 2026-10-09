"""Execution-policy gates use invented local inputs, never historical outcomes."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rf001_fixtures import label, module, schedule
from test_rf001_runner import manifest as fixture_manifest

os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def cancellation(gid="invented-cancelled", season=2011):
    return {
        "game_id": gid,
        "season": season,
        "week": 17,
        "game_type": "REG",
        "home_team": "CIN",
        "away_team": "BUF",
        "reason": "cancelled_no_contest",
        "source_row_present": False,
        "audit_ref": "https://operations.nfl.com/invented-cancellation-reference",
    }


def policy(*, real=True):
    years = list(range(2006, 2024)) if real else [2011]
    populations = {}
    for season in years:
        scheduled = (267 if season < 2020 else 269 if season == 2020 else 285) if real else 3
        excluded = int(season == (2022 if real else 2011))
        populations[str(season)] = {
            "documented_scheduled": scheduled,
            "retained_completed": scheduled - excluded,
            "externally_excluded": excluded,
        }
    external = cancellation("2022_17_BUF_CIN", 2022) if real else cancellation()
    return {
        "schema_version": 1,
        "policy_id": "rf001-reconstructed-2006-2023-v1",
        "input_seasons": years,
        "baseline_replay_start": 2006,
        "candidate_fit_start": 2006,
        "baseline_extra_history": "none",
        "cancellation_policy": "exclude_no_contest_from_completed_game_cohort",
        "population_accounting": {
            field: sum(x[field] for x in populations.values())
            for field in ("documented_scheduled", "retained_completed", "externally_excluded")
        }
        | {"per_season": populations},
        "external_population_exclusions": [external],
    }


def real_declarations(tmp_path):
    parts = [
        {
            "path": f"{kind}-{season}.csv",
            "season": season,
            "kind": kind,
            "role": "development",
            "sha256": "a" * 64,
            "audit": {"season_isolated": True, "kickoff_and_label_coverage_reviewed": True},
        }
        for season in range(2006, 2024)
        for kind in ("schedules", "labels")
    ]
    doc = {
        "schema_version": 1,
        "synthetic": False,
        "cohort": "reconstructed_scores",
        "partitions": parts,
        "execution_policy": policy(),
        "postseason_rule_metadata": {
            str(season): {
                "season": season,
                "no_final_ties": True,
                "reviewed": True,
                "sources": [f"https://operations.nfl.com/invented-rules-{season}"],
            }
            for season in range(2006, 2024)
        },
    }
    path = tmp_path / "manifest.json"
    return path, doc


@pytest.mark.parametrize(
    "mutation",
    [
        "absent",
        "extra_history",
        "start",
        "missing_kind",
        "duplicate_kind",
        "changed_total",
        "changed_year",
        "bad_cancel",
        "bad_population_sum",
        "missing_rule",
        "string_rule",
        "wrong_rule_year",
        "unreviewed",
        "permits_post_ties",
        "no_rule_sources",
        "bad_rule_url",
    ],
)
def test_real_policy_and_rule_gates_precede_every_game_artifact_read(
    tmp_path, monkeypatch, mutation
):
    path, doc = real_declarations(tmp_path)
    p = doc["execution_policy"]
    if mutation == "absent":
        doc.pop("execution_policy")
    elif mutation == "extra_history":
        row = dict(doc["partitions"][0])
        row.update(season=1999, role="baseline_warmup", path="old.csv")
        doc["partitions"].append(row)
    elif mutation == "start":
        p["baseline_replay_start"] = 1999
    elif mutation == "missing_kind":
        doc["partitions"].pop()
    elif mutation == "duplicate_kind":
        row = dict(doc["partitions"][0])
        row["path"] = "duplicate.csv"
        doc["partitions"].append(row)
    elif mutation == "changed_total":
        p["population_accounting"]["retained_completed"] -= 1
    elif mutation == "changed_year":
        p["input_seasons"][0] = 2007
    elif mutation == "bad_cancel":
        p["external_population_exclusions"][0]["home_team"] = "BUF"
    elif mutation == "bad_population_sum":
        p["population_accounting"]["per_season"]["2011"]["documented_scheduled"] += 1
    else:
        rule = doc["postseason_rule_metadata"]["2011"]
        if mutation == "missing_rule":
            doc["postseason_rule_metadata"].pop("2011")
        elif mutation == "string_rule":
            doc["postseason_rule_metadata"]["2011"] = "unreviewed text"
        elif mutation == "wrong_rule_year":
            rule["season"] = 2012
        elif mutation == "unreviewed":
            rule["reviewed"] = False
        elif mutation == "permits_post_ties":
            rule["no_final_ties"] = False
        elif mutation == "no_rule_sources":
            rule["sources"] = []
        elif mutation == "bad_rule_url":
            rule["sources"] = ["not-a-source-url"]
    path.write_text(json.dumps(doc))
    monkeypatch.setattr(
        Path, "read_bytes", lambda _: pytest.fail("Game artifact opened before policy gate")
    )
    with pytest.raises(ValueError, match="policy|population|partition|rule|cancellation|2006"):
        module("lab.backtest.score_data").load_manifest(path, require_execution_policy=True)


def tiny_input(tmp_path):
    dates = [datetime(2011, 9, 1, 17, tzinfo=UTC), datetime(2011, 9, 8, 17, tzinfo=UTC)]
    schedules = [schedule(f"invented-{i}", dt) for i, dt in enumerate(dates)]
    labels = [label(f"invented-{i}", dt) for i, dt in enumerate(dates)]
    path = fixture_manifest(tmp_path, schedules, labels)
    doc = json.loads(path.read_text())
    doc["execution_policy"] = policy(real=False)
    path.write_text(json.dumps(doc))
    return path, doc, schedules, labels


@pytest.mark.parametrize("identity_source", ["schedule", "unavailable_schedule", "label"])
def test_external_cancellation_cannot_overlap_any_input_identity(tmp_path, identity_source):
    _, doc, schedules, labels = tiny_input(tmp_path)
    excluded = doc["execution_policy"]["external_population_exclusions"][0]
    excluded["game_id"] = "invented-0"
    data = module("lab.backtest.score_data")
    if identity_source == "schedule":
        ds = data.Dataset.from_rows(schedules, [], "reconstructed_scores")
    elif identity_source == "unavailable_schedule":
        schedules[0]["kickoff_ts_utc"] = ""
        ds = data.Dataset.from_rows(schedules, labels, "reconstructed_scores")
    else:
        parsed = data.Dataset.from_rows(schedules, labels, "reconstructed_scores")
        ds = data.Dataset([], parsed.labels, "reconstructed_scores", [], "fetched_ts")
    with pytest.raises(ValueError, match="external.*overlap|overlap.*external"):
        data.validate_population(ds, doc)


def test_actual_completed_population_reconciles_and_fails_on_missing_labels(tmp_path):
    path, doc, schedules, labels = tiny_input(tmp_path)
    data = module("lab.backtest.score_data")
    ds = data.Dataset.from_rows(schedules, labels, "reconstructed_scores")
    data.validate_population(ds, doc)
    labels[0]["completed"] = False
    bad = data.Dataset.from_rows(schedules, labels, "reconstructed_scores")
    with pytest.raises(ValueError, match="population|completed"):
        data.validate_population(bad, doc)
    loaded, _ = data.load_manifest(path)
    assert len(loaded.targets()) == 2


def test_complete_fixed_real_declarations_are_admitted_without_reading_or_fitting(tmp_path):
    _, doc = real_declarations(tmp_path)
    module("lab.backtest.score_data").validate_execution_policy(doc)
    accounting = doc["execution_policy"]["population_accounting"]
    assert accounting["documented_scheduled"] == 4862
    assert accounting["retained_completed"] == 4861
    assert accounting["externally_excluded"] == 1


def test_external_population_saved_and_reported_without_prediction_or_fake_kickoff(tmp_path):
    path, doc, _, _ = tiny_input(tmp_path / "input")
    runner = module("lab.backtest.nfl_score")
    output = runner.run(path, tmp_path / "runs", "synthetic-population")
    p = doc["execution_policy"]
    ledger = json.loads((output / "external_population_exclusions.json").read_text())
    assert ledger == p["external_population_exclusions"]
    assert not {"kickoff", "kickoff_ts_utc", "as_of", "location"} & ledger[0].keys()
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["population_accounting"] == p["population_accounting"]
    assert metrics["external_population_exclusions"] == ledger
    predictions = [
        json.loads(line) for line in (output / "predictions.jsonl").read_text().splitlines()
    ]
    assert all(row["game_id"] != ledger[0]["game_id"] for row in predictions)
    assert metrics["outer"]["rf001"]["attempted"] == 0  # Tiny fixture is warm-up only.


def test_invalid_actual_population_refused_before_run_directory(tmp_path):
    path, doc, _, _ = tiny_input(tmp_path / "input")
    doc["execution_policy"]["population_accounting"]["retained_completed"] = 1
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="population"):
        module("lab.backtest.nfl_score").run(path, tmp_path / "runs", "refused")
    assert not (tmp_path / "runs").exists()


def test_read_only_archive_loading_keeps_policy_optional(tmp_path):
    path, doc, _, _ = tiny_input(tmp_path)
    doc.pop("execution_policy")
    path.write_text(json.dumps(doc))
    ds, _ = module("lab.backtest.score_data").load_manifest(path)
    assert len(ds.targets()) == 2
