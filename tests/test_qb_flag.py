"""QB-001 backup-QB flag on synthetic data; these are invented teams, QBs and outcomes."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from lab.backtest import qb_flag
from lab.backtest.nfl_score import frozen_predictions
from lab.backtest.score_data import Dataset
from lab.features import nfl as frozen
from lab.models import nfl_elo
from lab.store.db import connect, init_schema
from rf001_fixtures import label, schedule

START = datetime(2010, 9, 1, 17, tzinfo=UTC)


def season_games(n, qbs, start=START):
    """n weekly AAA-vs-BBB games; qbs[i] = (AAA starter, BBB starter)."""
    schedules, labels, starters = [], [], {}
    for i in range(n):
        kickoff = start + timedelta(days=7 * i)
        gid = f"g{i:03d}"
        home, away = ("AAA", "BBB") if i % 2 == 0 else ("BBB", "AAA")
        schedules.append(schedule(gid, kickoff, week=i + 1, home_team=home, away_team=away))
        labels.append(label(gid, kickoff, home_score=20 + i % 3, away_score=17 + i % 5))
        a, b = qbs[i]
        starters[gid] = {
            "home_team": home,
            "away_team": away,
            "home_qb": a if home == "AAA" else b,
            "away_qb": b if home == "AAA" else a,
        }
    return Dataset.from_rows(schedules, labels, "reconstructed_scores"), starters


# Usual-starter rule


def test_usual_starter_most_starts_in_last_eight():
    assert qb_flag.usual_starter(["A"] * 5 + ["B"] * 3) == "A"
    # Only the last 8 count: 10 old B starts are outside the window.
    assert qb_flag.usual_starter(["B"] * 10 + ["A"] * 5 + ["B"] * 3) == "A"


def test_three_game_backup_stint_flags_backup_then_returns_to_starter():
    starts = ["A"] * 10
    for _ in range(3):
        assert qb_flag.usual_starter(starts) == "A"  # backup B is flagged each game
        starts.append("B")
    assert qb_flag.usual_starter(starts) == "A"  # A returns: 5 A vs 3 B, not flagged


def test_offseason_starter_change_is_flagged_until_he_leads_the_window():
    starts = ["OLD"] * 17  # previous season, counted across seasons
    usual = []
    for _ in range(6):
        usual.append(qb_flag.usual_starter(starts))
        starts.append("NEW")
    # NEW is flagged in his first 4 games (0-3 of 8 is behind OLD; 4-4 ties go to NEW).
    assert usual == ["OLD", "OLD", "OLD", "OLD", "NEW", "NEW"]


def test_ties_go_to_most_recent_starter():
    assert qb_flag.usual_starter(["A", "B"] * 4) == "B"
    assert qb_flag.usual_starter(["B", "A"] * 4) == "A"
    assert qb_flag.usual_starter(["A", "A", "B", "B", "C", "C", "B", "A"]) == "A"


def test_no_prior_games_and_missing_ids_give_no_usual_starter():
    assert qb_flag.usual_starter([]) is None
    assert qb_flag.usual_starter([None, None]) is None


def test_missing_prior_ids_do_not_count_toward_the_eight():
    # Without skipping, the window would be [B, None x7] -> B. Skipped, the last 8
    # starts with an ID are 7 A and 1 B.
    assert qb_flag.usual_starter(["A"] * 7 + ["B"] + [None] * 7) == "A"


def test_fewer_than_eight_prior_games_use_what_exists():
    assert qb_flag.usual_starter(["A", "B", "B"]) == "B"


# Flags on a dataset


def test_flags_each_team_on_its_own_and_missing_ids_give_no_flag():
    qbs = [("A1", "B1")] * 4 + [("A2", "B1"), ("A1", None), (None, "B2"), ("A2", "B2")]
    dataset, starters = season_games(8, qbs)
    games = dataset.targets()
    flags = [qb_flag.backup_flags(g, dataset.eligible(g.as_of), starters) for g in games]
    by_team = [
        (
            f["home"] if g.home_team == "AAA" else f["away"],
            f["home"] if g.home_team == "BBB" else f["away"],
        )
        for g, f in zip(games, flags, strict=True)
    ]
    # Game 0 has no prior games; game 5 BBB and game 6 AAA have missing IDs.
    assert by_team == [
        (False, False),
        (False, False),
        (False, False),
        (False, False),
        (True, False),
        (False, False),
        (False, True),
        (True, True),
    ]
    assert flags[0]["home_usual"] is None and flags[5]["home_tonight"] is None


def test_unknown_game_ids_are_missing_ids():
    dataset, starters = season_games(3, [("A1", "B1")] * 3)
    del starters["g000"]
    del starters["g002"]
    game = dataset.targets()[2]
    flags = qb_flag.backup_flags(game, dataset.eligible(game.as_of), starters)
    assert not flags["home"] and not flags["away"] and flags["home_tonight"] is None


# No information from the target game or later games


def test_target_or_later_games_in_history_are_refused():
    dataset, starters = season_games(4, [("A1", "B1")] * 4)
    games = dataset.targets()
    everything = dataset.eligible(games[-1].kickoff + timedelta(days=1))
    with pytest.raises(ValueError, match="target or later"):
        qb_flag.backup_flags(games[1], everything, starters)


def test_rows_do_not_change_when_later_games_change():
    qbs = [("A1", "B1")] * 6 + [("A2", "B1")] * 4
    dataset, starters = season_games(10, qbs)
    before = qb_flag.score_games(dataset, starters)
    later = {f"g{i:03d}" for i in range(6, 10)}
    changed = {
        gid: {**s, "home_qb": "Z9", "away_qb": "Z8"} if gid in later else s
        for gid, s in starters.items()
    }
    schedules = [
        schedule(g.game_id, g.kickoff, week=g.week, home_team=g.home_team, away_team=g.away_team)
        for g in dataset.games
    ]
    labels = [
        label(
            x.game_id,
            next(g.kickoff for g in dataset.games if g.game_id == x.game_id),
            home_score=0 if x.game_id in later else x.home_score,
            away_score=40 if x.game_id in later else x.away_score,
        )
        for x in dataset.labels
    ]
    altered = Dataset.from_rows(schedules, labels, "reconstructed_scores")
    after = qb_flag.score_games(altered, changed)
    for a, b in zip(before[:6], after[:6], strict=True):
        assert {k: v for k, v in a.items() if k != "y"} == {k: v for k, v in b.items() if k != "y"}
    assert before[6]["p"] != after[6]["p"]  # sanity: the target game's own QB is used


# Probabilities


def test_penalty_zero_reproduces_frozen_elo_exactly():
    qbs = [("A1", "B1")] * 5 + [("A2", "B2")] * 3 + [("A1", "B2")] * 4
    dataset, starters = season_games(12, qbs)
    rows = qb_flag.score_games(dataset, starters)
    assert any(r["home_flag"] or r["away_flag"] for r in rows)
    for game, row in zip(dataset.targets(), rows, strict=True):
        expected = frozen_predictions(dataset.eligible(game.as_of), game)["elo"]
        assert row["p_elo"] == expected
        assert row["p"][0] == expected
    assert qb_flag.adjusted_probability(0.6891504797784799, 0.0, 0.0) == 0.6891504797784799


def test_penalty_subtracts_from_flagged_team_rating_only():
    con = connect(":memory:")
    init_schema(con)
    con.executemany(
        """INSERT INTO nfl_game (game_id, season, kickoff_ts, home_team, away_team,
           home_score, away_score, location) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("x1", 2025, "2025-09-07 17:00", "DAL", "TB", 28, 10, "Home"),
            ("x2", 2025, "2025-09-14 17:00", "NYG", "DAL", 17, 24, "Home"),
        ],
    )
    as_of = datetime(2025, 9, 20, tzinfo=UTC)
    ratings = frozen.elo_ratings(con, as_of, 2025)
    p0 = frozen.win_prob(con, "DAL", "TB", as_of, 2025)
    for home_pen, away_pen in ((125.0, 0.0), (0.0, 75.0), (200.0, 200.0)):
        direct = nfl_elo.expected_home(ratings["DAL"] - home_pen, ratings["TB"] - away_pen)
        assert qb_flag.adjusted_probability(p0, home_pen, away_pen) == pytest.approx(
            direct, abs=1e-12
        )
    assert qb_flag.adjusted_probability(p0, 125.0, 0.0) < p0
    assert qb_flag.adjusted_probability(p0, 0.0, 125.0) > p0
    con.close()


def test_grid_is_zero_to_eight_points_at_25_elo():
    qbs = [("A1", "B1")] * 4 + [("A2", "B1")]
    dataset, starters = season_games(5, qbs)
    row = qb_flag.score_games(dataset, starters)[-1]
    assert qb_flag.PENALTIES == tuple(range(9)) and qb_flag.ELO_PER_POINT == 25.0
    flagged_home = row["home_team"] == "AAA"
    for points, p in zip(qb_flag.PENALTIES, row["p"], strict=True):
        pen = points * 25.0
        expected = qb_flag.adjusted_probability(
            row["p_elo"], pen if flagged_home else 0.0, 0.0 if flagged_home else pen
        )
        assert p == expected


def test_choose_penalty_lowest_brier_and_ties_go_smaller():
    assert qb_flag.choose_penalty({0: 0.23, 1: 0.22, 2: 0.21, 3: 0.215}) == 2
    assert qb_flag.choose_penalty({0: 0.23, 3: 0.21, 5: 0.21, 8: 0.22}) == 3


# Source file


def test_load_starters_checks_hash_skips_holdout_and_maps_missing(tmp_path):
    text = (
        "game_id,season,home_team,away_team,home_qb_id,away_qb_id\n"
        "2010_01_OAK_SD,2010,SD,OAK,00-1,NA\n"
        "2023_01_A_B,2023,STL,DAL,,00-2\n"
        "2024_01_A_B,2024,KC,BAL,00-3,00-4\n"
        "2005_01_A_B,2005,KC,BAL,00-5,00-6\n"
    )
    path = tmp_path / "games.csv"
    path.write_text(text)
    sha = hashlib.sha256(text.encode()).hexdigest()
    starters = qb_flag.load_starters(path, expected_sha256=sha)
    assert starters == {
        "2010_01_OAK_SD": {
            "home_team": "LAC",
            "away_team": "LV",
            "home_qb": "00-1",
            "away_qb": None,
        },
        "2023_01_A_B": {"home_team": "LA", "away_team": "DAL", "home_qb": None, "away_qb": "00-2"},
    }
    with pytest.raises(ValueError, match="hash"):
        qb_flag.load_starters(path)
