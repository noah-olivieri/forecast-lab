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


# QB-002: new starters who started every game this season are not flagged


def two_seasons(qbs_by_season):
    """Weekly AAA-vs-BBB games per season; qbs[i] = (AAA starter, BBB starter)."""
    schedules, labels, starters = [], [], {}
    for season, qbs in qbs_by_season.items():
        start = datetime(season, 9, 1, 17, tzinfo=UTC)
        for i, (a, b) in enumerate(qbs):
            kickoff = start + timedelta(days=7 * i)
            gid = f"{season}_{i:02d}"
            home, away = ("AAA", "BBB") if i % 2 == 0 else ("BBB", "AAA")
            schedules.append(
                schedule(gid, kickoff, season=season, week=i + 1, home_team=home, away_team=away)
            )
            labels.append(
                label(gid, kickoff, season=season, home_score=20 + i % 3, away_score=17 + i % 5)
            )
            starters[gid] = {
                "home_team": home,
                "away_team": away,
                "home_qb": a if home == "AAA" else b,
                "away_qb": b if home == "AAA" else a,
            }
    return Dataset.from_rows(schedules, labels, "reconstructed_scores"), starters


def aaa_flags(rows, key):
    return [r[f"home_{key}"] if r["home_team"] == "AAA" else r[f"away_{key}"] for r in rows]


def test_new_starter_who_started_every_game_this_season_is_not_flagged():
    dataset, starters = two_seasons({2010: [("OLD", "B1")] * 10, 2011: [("NEW", "B1")] * 6})
    rows = qb_flag.score_games(dataset, starters, new_starter_rule=True)[10:]
    assert aaa_flags(rows, "flag") == [True] * 4 + [False] * 2  # QB-001 flags his first 4
    assert aaa_flags(rows, "flag_v2") == [False] * 6


def test_mid_season_fill_in_is_still_flagged():
    season = [("A1", "B1")] * 5 + [("FILL", "B1")] * 2 + [("A1", "B1")]
    dataset, starters = two_seasons({2010: [("A1", "B1")] * 8, 2011: season})
    rows = qb_flag.score_games(dataset, starters, new_starter_rule=True)[8:]
    assert aaa_flags(rows, "flag_v2") == [False] * 5 + [True, True, False]
    assert aaa_flags(rows, "flag_v2") == aaa_flags(rows, "flag")


def test_week_one_is_never_flagged():
    dataset, starters = two_seasons({2010: [("A1", "B1")] * 8, 2011: [("A2", "B2")]})
    row = qb_flag.score_games(dataset, starters, new_starter_rule=True)[-1]
    assert row["home_flag"] and row["away_flag"]  # QB-001 flags both new starters
    assert not row["home_flag_v2"] and not row["away_flag_v2"]
    assert row["p_v2"] == [row["p_elo"]] * len(qb_flag.PENALTIES)


def test_season_opening_backup_stint_is_not_flagged_and_starter_returns_unflagged():
    season = [("BACK", "B1")] * 3 + [("A1", "B1")] * 2
    dataset, starters = two_seasons({2010: [("A1", "B1")] * 8, 2011: season})
    rows = qb_flag.score_games(dataset, starters, new_starter_rule=True)[8:]
    assert aaa_flags(rows, "flag") == [True] * 3 + [False] * 2
    assert aaa_flags(rows, "flag_v2") == [False] * 5


def test_missing_ids_this_season_are_skipped():
    season = [("NEW", "B1"), (None, "B1"), ("NEW", "B1"), ("NEW", "B1")]
    dataset, starters = two_seasons({2010: [("OLD", "B1")] * 8, 2011: season})
    rows = qb_flag.score_games(dataset, starters, new_starter_rule=True)[8:]
    assert aaa_flags(rows, "flag") == [True, False, True, True]
    assert aaa_flags(rows, "flag_v2") == [False] * 4
    # Every earlier game this season missing: counts as starting every one (clarification 2).
    season = [(None, "B1"), (None, "B1"), ("NEW", "B1")]
    dataset, starters = two_seasons({2010: [("OLD", "B1")] * 8, 2011: season})
    row = qb_flag.score_games(dataset, starters, new_starter_rule=True)[-1]
    assert aaa_flags([row], "flag") == [True] and aaa_flags([row], "flag_v2") == [False]


def test_new_starter_rule_rows_do_not_change_when_later_games_change():
    season = [("NEW", "B1")] * 3 + [("FILL", "B1")] * 3
    dataset, starters = two_seasons({2010: [("OLD", "B1")] * 8, 2011: season})
    before = qb_flag.score_games(dataset, starters, new_starter_rule=True)
    later = {f"2011_{i:02d}" for i in range(3, 6)}
    changed = {
        gid: {**s, "home_qb": "Z9", "away_qb": "Z8"} if gid in later else s
        for gid, s in starters.items()
    }
    after = qb_flag.score_games(dataset, changed, new_starter_rule=True)
    assert before[:11] == after[:11]
    assert before[11] != after[11]
    game = dataset.targets()[9]
    everything = dataset.eligible(dataset.targets()[-1].kickoff + timedelta(days=1))
    with pytest.raises(ValueError, match="target or later"):
        qb_flag.backup_flags(game, everything, starters, new_starter_rule=True)


def test_default_is_qb001_and_rule_only_adds_v2_fields():
    season = [("NEW", "B1")] * 3 + [("FILL", "B2")] * 2
    dataset, starters = two_seasons({2010: [("OLD", "B1")] * 8, 2011: season})
    default = qb_flag.score_games(dataset, starters)
    extended = qb_flag.score_games(dataset, starters, new_starter_rule=True)
    v2_keys = {"home_flag_v2", "away_flag_v2", "home_exempt", "away_exempt", "p_v2"}
    assert all(not v2_keys & r.keys() for r in default)
    assert [{k: v for k, v in r.items() if k not in v2_keys} for r in extended] == default


# Saved QB-001 run (local research data; skipped where it is absent, such as CI)

RUN = qb_flag.ROOT / "data/research/runs/qb001-backup-flag-v1"
MANIFEST = (
    qb_flag.ROOT / "data/research/inputs/nfldata-93a5221-rf001-2006-2023-v1/execution-manifest.json"
)
ODDS = qb_flag.ROOT / "data/research/odds/nfldata-93a5221-moneyline-2006-2023-v2/manifest.json"
GAMES_CSV = (
    qb_flag.ROOT
    / "data/research/sources/nfldata-93a5221070bcd1733fe3c55abb48e931b3615241/games.csv"
)
saved_run = pytest.mark.skipif(
    not all(p.exists() for p in (RUN / "games.jsonl", MANIFEST, ODDS, GAMES_CSV)),
    reason="local QB-001 research run not present",
)


@pytest.fixture(scope="module")
def saved_qb001():
    import json

    from lab.backtest.score_data import load_manifest

    dataset, _ = load_manifest(MANIFEST, require_execution_policy=True)
    rows = [json.loads(line) for line in (RUN / "games.jsonl").read_text().splitlines()]
    return (
        dataset,
        qb_flag.load_starters(GAMES_CSV),
        rows,
        json.loads((RUN / "metrics.json").read_text()),
    )


@saved_run
def test_default_matches_saved_qb001_flags_on_every_game(saved_qb001):
    dataset, starters, saved, _ = saved_qb001
    keys = ("home_flag", "away_flag", "home_usual", "home_tonight", "away_usual", "away_tonight")
    targets = dataset.targets()
    assert [g.game_id for g in targets] == [r["game_id"] for r in saved]
    for game, row in zip(targets, saved, strict=True):
        flags = qb_flag.backup_flags(game, dataset.eligible(game.as_of), starters)
        assert tuple(
            flags[k.replace("_flag", "")] if k.endswith("_flag") else flags[k] for k in keys
        ) == tuple(row[k] for k in keys)


@saved_run
def test_default_matches_saved_qb001_rows_on_sample_games(saved_qb001):
    dataset, starters, saved, _ = saved_qb001
    by_id = {r["game_id"]: r for r in saved}
    targets = dataset.targets()
    flagged = [g for g in targets if by_id[g.game_id]["home_flag"] or by_id[g.game_id]["away_flag"]]
    sample = targets[:: len(targets) // 6] + flagged[:: len(flagged) // 6]
    for game in sample:
        assert qb_flag.score_game(dataset, game, starters) == by_id[game.game_id]


@saved_run
def test_qb001_report_reproduces_saved_metrics(saved_qb001):
    from lab.backtest.nfl_moneyline import load_odds_partitions

    _, _, saved, metrics = saved_qb001
    import json

    report = json.loads(qb_flag.canonical(qb_flag.report(saved, load_odds_partitions(ODDS))))
    assert report == metrics


def test_qb002_report_scores_each_model_at_its_own_penalty():
    tune = [("A1", "B1")] * 6 + [("A2", "B1")] * 3 + [("A1", "B1")] * 3
    test = [("NEW", "B1")] * 5 + [("FILL", "B2")] * 2 + [("NEW", "B1")] * 3
    dataset, starters = two_seasons({2013: tune, 2014: tune, 2015: test})
    rows = qb_flag.score_games(dataset, starters, new_starter_rule=True)
    result = qb_flag.report_v2(rows, {})
    tuned = [r for r in rows if r["season"] < 2015]
    grid = {
        name: {
            p: sum(qb_flag.probability_losses(r[key][i], r["y"])["brier"] for r in tuned)
            / len(tuned)
            for i, p in enumerate(qb_flag.PENALTIES)
        }
        for name, key in (("qb001", "p"), ("qb002", "p_v2"))
    }
    k1, k2 = (qb_flag.choose_penalty(grid[n]) for n in ("qb001", "qb002"))
    assert (result["qb001_penalty_points"], result["qb002_penalty_points"]) == (k1, k2)
    scored = [r for r in rows if r["season"] == 2015]
    primary = result["primary_qb002_minus_qb001"]["brier"]
    assert primary["n"] == len(scored) == 10
    expected = sum(
        (r["p_v2"][k2] - r["y"]) ** 2 - (r["p"][k1] - r["y"]) ** 2 for r in scored
    ) / len(scored)
    assert primary["mean"] == pytest.approx(expected, abs=1e-15)
    assert result["success"] is (primary["ci95"][1] < 0)
    # QB-001 flags NEW in 2015 games 1-3 (all exempt) and FILL/B2 in games 6-7 (not exempt).
    assert result["test"]["exempted_team_flags"] == 3
    assert result["test"]["qb001_team_flags"] == 3 + 4


def test_qb002_report_uses_different_penalties_when_chosen(monkeypatch):
    tune = [("A1", "B1")] * 6 + [("A2", "B1")] * 3 + [("A1", "B1")] * 3
    test = [("NEW", "B1")] * 5 + [("FILL", "B1")] * 2 + [("NEW", "B1")] * 3
    dataset, starters = two_seasons({2014: tune, 2015: test})
    rows = qb_flag.score_games(dataset, starters, new_starter_rule=True)
    picks = iter((1, 6))
    monkeypatch.setattr(qb_flag, "choose_penalty", lambda grid: next(picks))
    result = qb_flag.report_v2(rows, {})
    assert (result["qb001_penalty_points"], result["qb002_penalty_points"]) == (1, 6)
    scored = [r for r in rows if r["season"] == 2015]
    assert any(r["p_v2"][6] != r["p_v2"][1] for r in scored)  # one-sided flags
    expected = sum((r["p_v2"][6] - r["y"]) ** 2 - (r["p"][1] - r["y"]) ** 2 for r in scored) / len(
        scored
    )
    assert result["primary_qb002_minus_qb001"]["brier"]["mean"] == pytest.approx(
        expected, abs=1e-15
    )
