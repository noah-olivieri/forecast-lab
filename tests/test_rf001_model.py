from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from rf001_fixtures import label, module, schedule


def model():
    return module("lab.models.nfl_score")


def observations(schedules, labels):
    return (
        module("lab.backtest.score_data")
        .Dataset.from_rows(schedules, labels, "reconstructed_scores")
        .eligible(datetime(2023, 1, 1, tzinfo=UTC))
    )


def test_opponent_shrinkage_mean_loss_penalty_and_duplicate_weight_invariance():
    rows = observations([schedule(location="Neutral")], [label(home_score=30, away_score=10)])
    fit = model().fit_score(rows, datetime(2012, 1, 1, tzinfo=UTC), penalty=1, half_life=None)
    assert fit.predict("AAA", "BBB", True) == pytest.approx((25, 15))
    # Two effects of +/-2.5, intercept 20: (10-2x)^2 + 4*x^2 is minimized at x=2.5.
    assert fit.predict("UNSEEN", "UNSEEN2", True) == pytest.approx((20, 20))
    repeated = model().fit_score(rows * 4, datetime(2012, 1, 1, tzinfo=UTC), 1, None)
    assert repeated.predict("AAA", "BBB", True) == pytest.approx((25, 15))
    assert fit.home_bonus == 0  # no identifiable home rows


def test_league_home_bonus_neutral_and_age_weights():
    kick = datetime(2010, 9, 1, 17, tzinfo=UTC)
    obs = observations(
        [schedule("old", kick), schedule("new", kick + timedelta(days=365))],
        [
            label("old", kick, home_score=22, away_score=10),
            label("new", kick + timedelta(days=365), home_score=30, away_score=18),
        ],
    )
    fit = model().fit_score(obs, kick + timedelta(days=400), 1, 365, league=True)
    # League reference is always no-decay, independently of candidate settings.
    assert fit.predict("AAA", "BBB", False) == pytest.approx((26, 14))
    assert fit.predict("AAA", "BBB", True) == pytest.approx((14, 14))
    weighted = model().fit_score(obs, kick + timedelta(days=400), 1e12, 365)
    assert weighted.predict("AAA", "BBB", False) == pytest.approx((82 / 3, 46 / 3), abs=1e-4)


def test_fit_rejects_future_observation_and_means_are_nonnegative():
    obs = observations([schedule()], [label()])
    with pytest.raises(ValueError, match="eligible"):
        model().fit_score(obs, obs[0].game.kickoff + timedelta(hours=4), 1, None)
    fit = model().fit_score(obs, datetime(2012, 1, 1, tzinfo=UTC), 1, None)
    assert min(fit.predict("AAA", "BBB", True)) >= 0


def test_paired_bank_order_covariance_and_stable_seed():
    bank = [
        {"game_id": "b", "kickoff": "2011-09-02T00:00:00Z", "residual": [-4, -8]},
        {"game_id": "a", "kickoff": "2011-09-01T00:00:00Z", "residual": [4, 8]},
    ]
    cutoff = datetime(2012, 1, 1, tzinfo=UTC)
    result = model().sample_scores((20, 20), bank, "g", cutoff, 7, "REG")
    permuted = model().sample_scores((20, 20), bank[::-1], "g", cutoff, 7, "REG")
    assert np.array_equal(result.samples, permuted.samples)
    assert result.samples.shape == (10000, 2)
    assert set(map(tuple, result.samples)) == {(24, 28), (16, 12)}
    assert np.cov(result.samples.T)[0, 1] > 30
    assert result.summary["p_tie"] == 0
    assert result.summary["p_home"] + result.summary["p_away"] == 1


def test_round_half_up_clip_and_support_approximation_diagnostics():
    bank = [{"game_id": "a", "kickoff": "2011-09-01T00:00:00Z", "residual": [0, 0]}]
    result = model().sample_scores((-2, 0.5), bank, "g", datetime(2012, 1, 1, tzinfo=UTC), 7, "REG")
    assert set(map(tuple, result.samples)) == {(0, 1)}
    assert result.summary["score_one_draws"] == 10000
    assert result.summary["one_below_six_opponent_draws"] == 10000
    assert result.summary["expected_home_points"] == 0
    assert result.summary["expected_total"] == 1
    assert result.summary["expected_margin"] == -1


def test_regular_ties_share_and_postseason_conditioning():
    bank = [
        {"game_id": "a", "kickoff": "2011-09-01T00:00:00Z", "residual": [0, 0]},
        {"game_id": "b", "kickoff": "2011-09-02T00:00:00Z", "residual": [1, -1]},
        {"game_id": "c", "kickoff": "2011-09-03T00:00:00Z", "residual": [-1, 1]},
    ]
    cutoff = datetime(2012, 1, 1, tzinfo=UTC)
    regular = model().sample_scores((20, 20), bank, "g", cutoff, 7, "REG")
    assert regular.summary["p_tie"] == pytest.approx(1 / 3, abs=0.02)
    assert regular.summary["p_share"] == (
        regular.summary["p_home"] + 0.5 * regular.summary["p_tie"]
    )
    post = model().sample_scores((20, 20), bank, "g", cutoff, 7, "POST")
    assert post.summary["p_tie"] == 0
    assert post.rejected > 0
    assert len(post.samples) == 10000
    with pytest.raises(model().DistributionUnavailable, match="non-tied"):
        model().sample_scores((20, 20), bank[:1], "g", cutoff, 7, "POST")
