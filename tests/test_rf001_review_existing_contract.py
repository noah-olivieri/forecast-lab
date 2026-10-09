"""Independent checks of review coverage gaps; these contracts already worked."""

import json
from datetime import UTC, datetime

import numpy as np
import pytest

from rf001_fixtures import history, label, module, schedule
from test_rf001_runner import manifest, read_lines, runner


def test_hand_calculated_energy_and_nonatom_pit():
    # Two atoms at distance 5: E||X-y||=(sqrt(8)+sqrt(5))/2,
    # half E||X-X'||=1.25, including the diagonal's zero distance.
    result = module("lab.eval.score_metrics").score_draws(np.array([[0, 0], [3, 4]]), (2, 2), 7)
    exact = (np.sqrt(8) + np.sqrt(5)) / 2 - 1.25
    assert result["energy"] == pytest.approx(exact, abs=0.06)
    assert result["energy_repeat"] == pytest.approx(exact, abs=0.06)
    assert result["home_pit"] == result["away_pit"] == result["total_pit"] == 0.5
    # Half the margin mass is below zero and half is exactly at zero.
    assert 0.5 <= result["margin_pit"] <= 1


def test_missed_tie_label_has_quarter_point_brier_upper_bound():
    kick = datetime(2015, 9, 1, tzinfo=UTC)
    ds = module("lab.backtest.score_data").Dataset.from_rows(
        [schedule("tie", kick)],
        [label("tie", kick, home_score=20, away_score=20)],
        "reconstructed_scores",
    )
    row = {
        "game_id": "tie",
        "model": "rf001",
        "role": "outer",
        "season": 2015,
        "status": "miss",
        "reason": "insufficient_training",
    }
    report = runner().metric_report([row], [], {"tie": ds.evaluation_label("tie")}, synthetic=True)
    assert report["outer"]["rf001"]["brier_eligible_bounds"] == [0, 0.25]


def test_four_week_blocks_stay_contiguous_within_each_season():
    rows = [
        {
            "game_id": f"{season}-{i}",
            "season": season,
            "week": i,
            "game_type": "REG",
            "kickoff": f"{season}-09-{i:02d}T00:00:00Z",
            "difference": value,
        }
        for season, values in [(2015, [1, 2, 3, 100]), (2016, [-100, -3, -2, -1])]
        for i, value in enumerate(values, 1)
    ]
    report = module("lab.eval.score_metrics").paired_bootstrap(rows, replicates=500)
    # A length-four block in a four-week season must take that entire season.
    assert report["ci95"] == [0, 0]
    assert report["one_week_ci95"][0] < 0 < report["one_week_ci95"][1]
    assert report["season_ci95"] == [-26.5, 26.5]


def test_neutral_postseason_forecast_uses_no_home_bonus_and_no_final_ties(tmp_path):
    schedules, labels = history(156)
    kick = datetime(2015, 2, 1, 23, tzinfo=UTC)
    schedules.append(
        schedule(
            "neutral-post", kick, home_team="T0", away_team="T1", game_type="SB", location="Neutral"
        )
    )
    labels.append(label("neutral-post", kick, home_score=31, away_score=24))
    path = runner().run(manifest(tmp_path / "input", schedules, labels), tmp_path / "runs", "post")
    row = next(
        r
        for r in read_lines(path / "predictions.jsonl")
        if r["game_id"] == "neutral-post" and r["model"] == "league"
    )
    audit = json.loads((path / row["fit_path"]).read_text())
    assert (
        row["fitted_home_mean"]
        == row["fitted_away_mean"]
        == pytest.approx(audit["coefficients"][0])
    )
    with np.load(path / row["samples_path"]) as saved:
        assert np.all(saved["samples"][:, 0] != saved["samples"][:, 1])
    assert row["p_tie"] == 0
    report = json.loads((path / "metrics.json").read_text())
    assert report["slices"]["league"]["postseason"]["scored"] == 1
    assert report["slices"]["league"]["neutral"]["scored"] == 1
