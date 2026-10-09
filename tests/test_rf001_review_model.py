from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from rf001_fixtures import history, label, module, schedule
from rf001_workloads import known_effect_league


def test_grid_recovers_known_effects_in_an_invented_balanced_league():
    schedules, labels, offense, defense = known_effect_league()
    data = module("lab.backtest.score_data")
    cutoff = datetime(2012, 1, 1, tzinfo=UTC)
    prior = data.Dataset.from_rows(schedules, labels, "reconstructed_scores").eligible(cutoff)
    least_penalty = min(s[0] for s in module("lab.backtest.nfl_score").GRID)
    fit = module("lab.models.nfl_score").fit_score(prior, cutoff, least_penalty, None)
    # Regression slope against independent known generating effects, not fit's own predictions.
    for truth, estimated in ((offense, fit.offense), (defense, fit.defense)):
        x = np.array(list(truth.values()))
        y = np.array([estimated[t] for t in truth])
        slope = float(x @ y / (x @ x))
        assert 0.75 <= slope <= 1.05


def test_three_team_hand_calculation_uses_opponent_defense():
    kick = datetime(2011, 1, 1, 17, tzinfo=UTC)
    rows, labels = [], []
    for i, (home, away, hs, aws) in enumerate(
        [("A", "B", 31, 18), ("A", "C", 23, 12), ("B", "C", 17, 19)]
    ):
        at = kick + timedelta(days=7 * i)
        rows.append(schedule(str(i), at, home_team=home, away_team=away, location="Neutral"))
        labels.append(label(str(i), at, home_score=hs, away_score=aws))
    cutoff = datetime(2012, 1, 1, tzinfo=UTC)
    prior = (
        module("lab.backtest.score_data")
        .Dataset.from_rows(rows, labels, "reconstructed_scores")
        .eligible(cutoff)
    )
    fit = module("lab.models.nfl_score").fit_score(prior, cutoff, 1 / 3, None)
    # Balanced three-team equations: o_hat=(7o-2d)/15, d_hat=(7d-2o)/15.
    # True o=(6,0,-6), d=(-2,5,-3), league mean=20.
    assert fit.predict("A", "B", True) == pytest.approx((25.4, 17.6))
    assert fit.predict("A", "C", True) == pytest.approx((337 / 15, 238 / 15))


def test_repredict_with_changed_prior_is_rejected_instead_of_stale_cache():
    schedules, labels = history(101)
    data = module("lab.backtest.score_data")
    ds = data.Dataset.from_rows(schedules, labels, "reconstructed_scores")
    game = ds.targets()[-1]
    engine = module("lab.backtest.nfl_score").ChronologicalEngine()
    engine.predict(game, ds.eligible(game.as_of), (0.001, None), 7)
    changed = [dict(x, home_score=50) if x["game_id"] == "synthetic-0000" else x for x in labels]
    revised = data.Dataset.from_rows(schedules, changed, "reconstructed_scores")
    with pytest.raises(ValueError, match="changed.*prior"):
        engine.predict(game, revised.eligible(game.as_of), (0.001, None), 7)


def test_changed_prior_cannot_replace_original_means_after_same_time_other_target():
    schedules, labels = history(101)
    last = schedules[-1]
    schedules.append(dict(last, game_id="other", home_team="X", away_team="Y"))
    data = module("lab.backtest.score_data")
    ds = data.Dataset.from_rows(schedules, labels, "reconstructed_scores")
    game = next(g for g in ds.targets() if g.game_id == "synthetic-0100")
    other = next(g for g in ds.targets() if g.game_id == "other")
    engine = module("lab.backtest.nfl_score").ChronologicalEngine()
    engine.predict(game, ds.eligible(game.as_of), (0.001, None), 7)
    engine.predict(other, ds.eligible(other.as_of), (0.001, None), 7)
    changed = [dict(x, home_score=50) if x["game_id"] == "synthetic-0000" else x for x in labels]
    revised = data.Dataset.from_rows(schedules, changed, "reconstructed_scores")
    with pytest.raises(ValueError, match="changed.*prior"):
        engine.predict(game, revised.eligible(game.as_of), (0.001, None), 7)
