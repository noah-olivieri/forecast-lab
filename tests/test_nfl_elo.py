import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from lab.features import nfl
from lab.ingest.nflverse import game_rows, upsert_games
from lab.models import nfl_elo as elo
from lab.store.db import connect, init_schema


def test_expected_home_even_teams_gets_home_field():
    p = elo.expected_home(1500, 1500, hfa=65)
    assert p == pytest.approx(1 / (1 + 10 ** (-65 / 400)))
    assert p == pytest.approx(0.5925, abs=1e-4)
    assert elo.expected_home(1500, 1500, hfa=0) == 0.5  # neutral site


def test_expected_is_complementary_with_flipped_sides():
    assert elo.expected_home(1600, 1450, 0) + elo.expected_home(1450, 1600, 0) == pytest.approx(1)


def test_winner_elo_diff_is_signed_and_includes_home_field():
    assert elo.winner_elo_diff(1500, 1500, 65, home_won=True) == 65
    assert elo.winner_elo_diff(1500, 1500, 65, home_won=False) == -65
    assert elo.winner_elo_diff(1600, 1500, 65, home_won=False) == -165  # away won as the underdog


def test_mov_multiplier_smaller_for_favorite_than_underdog():
    margin = 14
    even = elo.mov_multiplier(margin, 0)
    favorite = elo.mov_multiplier(margin, +200)  # winner was the 200-point favorite
    underdog = elo.mov_multiplier(margin, -200)  # winner was the 200-point underdog
    assert even == pytest.approx(math.log(15))
    assert favorite == pytest.approx(math.log(15) * 2.2 / 2.4)
    assert underdog == pytest.approx(math.log(15) * 2.2 / 2.0)
    assert favorite < even < underdog


def test_favorite_win_vs_underdog_win_through_update():
    # Home team is the 200-point favorite (after home field). Same 14-point margin both ways.
    h, a, hfa = 1635.0, 1500.0, 65.0  # h + hfa - a = 200
    fav_h, fav_a = elo.update(h, a, 24, 10, hfa)  # favorite wins
    dog_h, dog_a = elo.update(h, a, 10, 24, hfa)  # underdog wins
    p = elo.expected_home(h, a, hfa)
    mult_fav = elo.mov_multiplier(14, 200)
    mult_dog = elo.mov_multiplier(14, -200)
    assert mult_fav < mult_dog
    assert fav_h - h == pytest.approx(20 * mult_fav * (1 - p))
    assert dog_h - h == pytest.approx(20 * mult_dog * (0 - p))
    assert abs(fav_h - h) < abs(dog_h - h)  # smaller multiplier and smaller surprise
    assert fav_h + fav_a == pytest.approx(h + a) and dog_h + dog_a == pytest.approx(h + a)


def test_tie_leaves_ratings_unchanged():
    assert elo.update(1600, 1400, 20, 20) == (1600, 1400)


def test_regression_to_mean():
    out = elo.regress_to_mean({"A": 1600.0, "B": 1405.0})
    assert out["A"] == pytest.approx(1600 * 2 / 3 + 1505 / 3)
    assert out["B"] == pytest.approx(1405 * 2 / 3 + 1505 / 3)


# ---- as_of / leakage ----


def _row(gid, season, ts, home, away, hs, a_s, loc="Home"):
    return {
        "game_id": gid, "season": season, "week": 1, "game_type": "REG",
        "gameday": ts.strftime("%Y-%m-%d"), "gametime": ts.strftime("%H:%M"),
        "away_team": away, "home_team": home, "away_score": a_s, "home_score": hs,
        "location": loc,
    }  # fmt: skip


def _con(*games):
    """games as _row dicts; kickoff is read as Eastern wall-clock."""
    con = connect(":memory:")
    init_schema(con)
    upsert_games(con, game_rows(list(games)))
    return con


ET = ZoneInfo("America/New_York")
ET_T = datetime(2025, 9, 7, 13, 0, tzinfo=ET)  # only its Eastern wall-clock is used
UTC_KICK = datetime(2025, 9, 7, 17, 0, tzinfo=UTC)  # 13:00 EDT


def test_only_finished_games_move_ratings():
    con = _con(_row("g1", 2025, ET_T, "AAA", "BBB", 30, 10))
    before = UTC_KICK + timedelta(hours=3)  # still inside the 4h finish lag
    after = UTC_KICK + timedelta(hours=5)
    assert nfl.elo_ratings(con, before, 2025) == {}
    r = nfl.elo_ratings(con, after, 2025)
    assert r["AAA"] > 1500 > r["BBB"]


def test_future_game_and_its_score_cannot_change_features():
    g1 = _row("g1", 2025, ET_T, "AAA", "BBB", 30, 10)
    g2 = _row("g2", 2025, ET_T + timedelta(days=7), "BBB", "AAA", 3, 45)
    g2_alt = _row("g2", 2025, ET_T + timedelta(days=7), "BBB", "AAA", 45, 3)
    as_of = UTC_KICK + timedelta(days=3)
    a = nfl.elo_ratings(_con(g1, g2), as_of, 2025)
    b = nfl.elo_ratings(_con(g1, g2_alt), as_of, 2025)
    c = nfl.elo_ratings(_con(g1), as_of, 2025)
    assert a == b == c
    assert nfl.home_win_rate(_con(g1, g2), as_of) == nfl.home_win_rate(_con(g1, g2_alt), as_of)


def test_new_season_regresses_and_neutral_site_has_no_home_edge():
    g1 = _row("g1", 2024, datetime(2024, 9, 8, 13, 0, tzinfo=ET), "AAA", "BBB", 30, 10)
    con = _con(g1)
    as_of = datetime(2025, 9, 1, tzinfo=UTC)
    same = nfl.elo_ratings(con, as_of, 2024)
    nxt = nfl.elo_ratings(con, as_of, 2025)
    assert nxt["AAA"] == pytest.approx(same["AAA"] * 2 / 3 + 1505 / 3)
    assert nfl.win_prob(con, "AAA", "BBB", as_of, 2025, neutral=True) > 0.5
    assert nfl.win_prob(con, "CCC", "DDD", as_of, 2025, neutral=True) == 0.5
    assert nfl.win_prob(con, "CCC", "DDD", as_of, 2025) == pytest.approx(
        elo.expected_home(1500, 1500)
    )


def test_home_win_rate_skips_neutral_and_halves_ties():
    gs = [
        _row("g1", 2025, ET_T, "A", "B", 20, 10),
        _row("g2", 2025, ET_T + timedelta(days=1), "C", "D", 10, 10),
        _row("g3", 2025, ET_T + timedelta(days=2), "E", "F", 0, 30, loc="Neutral"),
    ]
    assert nfl.home_win_rate(_con(*gs), UTC_KICK + timedelta(days=9)) == pytest.approx(0.75)


def test_home_rate_baseline_is_half_at_neutral_site():
    gs = [_row(f"g{i}", 2025, ET_T + timedelta(days=i), "A", "B", 30, 10) for i in range(3)]
    con = _con(*gs)
    as_of = UTC_KICK + timedelta(days=9)
    assert nfl.home_win_rate(con, as_of) == 1.0  # home team won every game
    assert nfl.home_rate_baseline(con, as_of, neutral=False) == 1.0
    assert nfl.home_rate_baseline(con, as_of, neutral=True) == 0.5
