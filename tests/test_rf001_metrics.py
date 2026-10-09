import math

import numpy as np
import pytest

from rf001_fixtures import module


def metrics():
    return module("lab.eval.score_metrics")


def test_hand_calculated_crps_brier_log_loss_and_intervals():
    m = metrics()
    assert m.crps([0, 2], 1) == 0.5
    assert m.crps([0, 0, 2, 2], 1) == 0.5  # empirical V-statistic, not fair CRPS
    assert m.probability_losses(0.75, 0.5)["brier"] == 0.0625
    assert m.probability_losses(0.75, 0.5)["log_loss"] == pytest.approx(-0.5 * math.log(0.1875))
    assert m.probability_losses(1, 0)["clipped"] == 1
    assert m.probability_losses(1, 0)["brier"] == 1
    report = m.score_draws(np.array([[24, 14], [14, 24]]), (24, 14), 10)
    assert report["margin_crps"] == 5
    assert report["total_crps"] == 0
    assert report["home_mae"] == 5
    assert report["home_bias"] == -5
    assert report["margin_50_covered"] == 1
    assert report["margin_50_width"] == 20
    assert report["three_way_brier"] == 0.5
    assert 0 <= report["margin_pit"] <= 1
    assert report["energy_seed"] == 10


def test_paired_bootstrap_preserves_whole_weeks_and_actual_game_denominators():
    rows = [
        {
            "game_id": f"g{i}",
            "season": 2015,
            "week": i // 2 + 1,
            "game_type": "REG",
            "kickoff": f"2015-09-{i + 1:02d}T00:00:00Z",
            "difference": -2.0,
        }
        for i in range(8)
    ]
    report = metrics().paired_bootstrap(rows)
    assert report["n"] == 8
    assert report["mean"] == -2
    assert report["ci95"] == [-2, -2]
    assert report["one_week_ci95"] == [-2, -2]
    assert report["season_ci95"] == [-2, -2]
    assert report == metrics().paired_bootstrap(rows[::-1])
    rows.append(
        {
            "game_id": "post",
            "season": 2015,
            "week": 1,
            "game_type": "WC",
            "kickoff": "2016-01-01T00:00:00Z",
            "difference": -2,
        }
    )
    assert metrics().paired_bootstrap(rows)["week_count"] == 5


def test_tuning_tie_break_and_no_current_outer_labels():
    trials = [
        {"penalty": 1, "half_life": None, "losses": [{"season": 2012, "margin_crps": 2}]},
        {"penalty": 100, "half_life": 730, "losses": [{"season": 2012, "margin_crps": 2.0005}]},
        {"penalty": 100, "half_life": None, "losses": [{"season": 2012, "margin_crps": 2.0008}]},
        {"penalty": 10, "half_life": 365, "losses": [{"season": 2015, "margin_crps": 0}]},
    ]
    selected, ledger = metrics().select_setting(trials, 2015)
    assert selected == (100, None)
    assert ledger[-1]["status"] == "unavailable"
    trials[-1]["losses"][0]["margin_crps"] = 9999
    assert metrics().select_setting(trials, 2015)[0] == (100, None)


def test_bootstrap_pools_games_rather_than_averaging_unequal_week_means():
    differences = [(1, 0), (2, 10), (2, 10), (2, 10), (3, 20), (4, 30)]
    rows = [
        {
            "game_id": str(i),
            "season": 2015,
            "week": week,
            "game_type": "REG",
            "kickoff": f"2015-09-{week:02d}T00:00:00Z",
            "difference": loss,
        }
        for i, (week, loss) in enumerate(differences)
    ]
    result = metrics().paired_bootstrap(rows)
    assert result["mean"] == pytest.approx(80 / 6)
    assert result["ci95"] == pytest.approx([80 / 6, 80 / 6])
    assert result["one_week_ci95"][0] < result["one_week_ci95"][1]
