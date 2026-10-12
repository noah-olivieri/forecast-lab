"""Single-pass Elo replay vs the per-game frozen harness. Synthetic teams, QBs and scores."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab.backtest import elo_replay, qb_flag
from lab.backtest.nfl_score import frozen_predictions
from lab.backtest.score_data import Dataset
from rf001_fixtures import label, schedule

TOL = 1e-12
TEAMS_2010 = ("AAA", "BBB", "CCC", "DDD")
TEAMS_2011 = ("AAA", "BBB", "CCC", "EEE")  # DDD leaves, EEE is new


def league(change=None):
    """Two seasons of round-robin weeks with the cases the replay must get right.

    Sunday games at 17:00 and 20:25 UTC (the early result is not known at the late game's
    T-24h cutoff), a Thursday-night game that is known by Sunday's cutoff, a neutral site, a
    tie, a revised label, an incomplete label and a team that only exists in the second
    season. `change` maps a game_id to replacement scores.
    """
    schedules, labels, starters = [], [], {}
    pairs = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]

    def add(gid, season, week, kickoff, home, away, hs, a_s, **extra):
        hs, a_s = (change or {}).get(gid, (hs, a_s))
        schedules.append(
            schedule(
                gid,
                kickoff,
                season=season,
                week=week,
                home_team=home,
                away_team=away,
                **extra.pop("schedule", {}),
            )
        )
        labels.append(label(gid, kickoff, season=season, home_score=hs, away_score=a_s, **extra))
        n = int(gid[1:])
        starters[gid] = {
            "home_team": home,
            "away_team": away,
            "home_qb": f"{home}-{'b' if n % 7 == 3 else 'a'}",
            "away_qb": f"{away}-{'b' if n % 5 == 4 else 'a'}" if n % 11 else None,
        }

    n = 0
    for season, teams, start in (
        (2010, TEAMS_2010, datetime(2010, 9, 12, 17, tzinfo=UTC)),
        (2011, TEAMS_2011, datetime(2011, 9, 11, 17, tzinfo=UTC)),
    ):
        for week in range(1, 10):
            sunday = start + timedelta(days=7 * (week - 1))
            (a, b), (c, d) = pairs[week % 3]
            if week % 2:
                a, b, c, d = b, a, d, c
            first = sunday - timedelta(days=2, hours=17) if week == 4 else sunday  # Thu night ET
            add(f"g{n:03d}", season, week, first, teams[a], teams[b], 17 + n % 13, 20 + n % 7)
            n += 1
            extra = {}
            if week == 6:
                extra["schedule"] = {"location": "Neutral"}
            add(
                f"g{n:03d}",
                season,
                week,
                sunday + timedelta(hours=3, minutes=25),
                teams[c],
                teams[d],
                24 if week == 5 else 10 + n % 17,
                24 if week == 5 else 13,
                **extra,
            )
            n += 1
    # A revised label: the later fetched revision wins under the reconstructed cohort.
    gid = "g004"
    first = next(x for x in labels if x["game_id"] == gid)
    labels.append(
        {
            **first,
            "revision_id": "l2",
            "home_score": 3,
            "away_score": 30,
            "fetched_ts": (
                datetime.fromisoformat(first["fetched_ts"]) + timedelta(days=1)
            ).isoformat(),
        }
    )
    # An incomplete label: the game never enters history and has no evaluation label.
    for x in labels:
        if x["game_id"] == "g009":
            x.update(completed=False, home_score="", away_score="")
    return Dataset.from_rows(schedules, labels, "reconstructed_scores"), starters


def old_harness(dataset):
    return {
        g.game_id: frozen_predictions(dataset.eligible(g.as_of), g)["elo"]
        for g in dataset.targets()
    }


def test_no_hook_equals_frozen_elo_on_every_game():
    dataset, _ = league()
    rows = elo_replay.replay(dataset)
    assert [r["game_id"] for r in rows] == [g.game_id for g in dataset.targets()]
    old = old_harness(dataset)
    # Same float operations in the same order: equal, not just close.
    assert [r["p_elo"] for r in rows] == [old[r["game_id"]] for r in rows]
    assert all(r["p"] == r["p_elo"] and r["adj_home"] == r["adj_away"] == 0 for r in rows)


def test_fixture_exercises_the_edge_cases():
    dataset, _ = league()
    targets = dataset.targets()
    known = {g.game_id: {o.game.game_id for o in dataset.eligible(g.as_of)} for g in targets}
    by_id = {g.game_id: g for g in targets}
    # The Thursday game is known by Sunday's cutoff; the same-day 17:00 game is not.
    assert by_id["g007"].kickoff - by_id["g006"].kickoff > timedelta(days=2)
    assert "g006" in known["g007"]
    assert by_id["g008"].kickoff < by_id["g009"].kickoff and "g008" not in known["g009"]
    assert any(g.location == "Neutral" for g in targets)
    assert "EEE" in {t for g in targets if g.season == 2011 for t in (g.home_team, g.away_team)}
    assert dataset.evaluation_label("g009") is None and "g009" not in known[targets[-1].game_id]
    assert dataset.evaluation_label("g004").home_score == 3
    rows = {r["game_id"]: r for r in elo_replay.replay(dataset)}
    assert rows["g009"]["y"] is None and rows["g004"]["y"] == 0
    assert any(r["y"] == 0.5 for r in rows.values())


def test_labels_match_evaluation_label():
    dataset, _ = league()
    for row in elo_replay.replay(dataset):
        label = dataset.evaluation_label(row["game_id"])
        if label is None:
            assert row["y"] is None
        else:
            m = label.home_score - label.away_score
            assert row["y"] == (1 if m > 0 else 0 if m < 0 else 0.5)


def test_hook_sees_exactly_the_eligible_history_and_pregame_ratings():
    dataset, _ = league()
    seen = {}

    def hook(game, state):
        seen[game.game_id] = state
        return 0.0, 0.0

    rows = {r["game_id"]: r for r in elo_replay.replay(dataset, hook)}
    for game in dataset.targets():
        state = seen[game.game_id]
        assert state.history == tuple(dataset.eligible(game.as_of))
        assert all(o.game.kickoff + timedelta(hours=4) < game.as_of for o in state.history)
        row = rows[game.game_id]
        assert state.ratings.get(game.home_team, 1500.0) == row["elo_home"]
        assert state.ratings.get(game.away_team, 1500.0) == row["elo_away"]
        with pytest.raises(TypeError):
            state.ratings["AAA"] = 0.0  # read-only


def test_hook_shifts_only_the_forecast_never_the_ratings():
    dataset, _ = league()
    plain = elo_replay.replay(dataset)
    shifted = elo_replay.replay(dataset, lambda game, state: (40.0, -15.0))
    for a, b in zip(plain, shifted, strict=True):
        assert (a["elo_home"], a["elo_away"], a["p_elo"]) == (
            b["elo_home"],
            b["elo_away"],
            b["p_elo"],
        )
        assert b["p"] < a["p"]


@pytest.mark.parametrize("points", [0, 2, 8])
def test_qb001_hook_reproduces_qb001_rows(points):
    dataset, starters = league()
    rows = elo_replay.replay(dataset, elo_replay.qb001_hook(starters, points))
    old = qb_flag.score_games(dataset, starters)
    assert any(r["home_flag"] or r["away_flag"] for r in old)
    k = qb_flag.PENALTIES.index(points)
    for new, ref in zip(rows, old, strict=True):
        assert new["game_id"] == ref["game_id"]
        assert new["p_elo"] == ref["p_elo"]
        assert abs(new["p"] - ref["p"][k]) < TOL
        assert (new["adj_home"] > 0, new["adj_away"] > 0) == (
            points > 0 and ref["home_flag"],
            points > 0 and ref["away_flag"],
        )


@pytest.mark.parametrize("hooked", [False, True])
def test_changing_a_later_result_never_changes_an_earlier_forecast(hooked):
    dataset, starters = league()
    targets = dataset.targets()
    pivot = targets[len(targets) // 2]
    changed, _ = league({pivot.game_id: (0, 45)})
    hook = elo_replay.qb001_hook(starters, 8) if hooked else None
    before = elo_replay.replay(dataset, hook)
    after = elo_replay.replay(changed, hook)
    # Every game whose cutoff comes before the pivot's result is known.
    unknown = [g.as_of <= pivot.kickoff + timedelta(hours=4) for g in targets]
    assert any(unknown) and not all(unknown)
    for old, new, earlier in zip(before, after, unknown, strict=True):
        if earlier:
            if old["game_id"] == pivot.game_id:  # only its own label changes
                old, new = {**old, "y": None}, {**new, "y": None}
            assert old == new
    assert any(o["p"] != n["p"] for o, n, e in zip(before, after, unknown, strict=True) if not e)


def test_seasons_limit_rows_but_not_history():
    dataset, _ = league()
    full = elo_replay.replay(dataset)
    only = elo_replay.replay(dataset, seasons=range(2011, 2012))
    assert only == [r for r in full if r["season"] == 2011]


def test_strict_pit_is_refused():
    dataset, _ = league()
    strict = Dataset(dataset.games, dataset.labels, "strict_pit", [], "published_ts")
    with pytest.raises(ValueError, match="reconstructed_scores"):
        elo_replay.replay(strict)


def test_holdout_seasons_cannot_enter_a_dataset():
    kickoff = datetime(2024, 9, 8, 17, tzinfo=UTC)
    with pytest.raises(ValueError, match="locked holdout"):
        Dataset.from_rows([schedule("x", kickoff)], [label("x", kickoff)], "reconstructed_scores")
    assert elo_replay.MAX_SEASON == 2023


# The saved QB-001 run (data/ is local and gitignored). LAB_RESEARCH_ROOT points a worktree
# at the checkout that holds data/.
ROOT = Path(os.environ.get("LAB_RESEARCH_ROOT", qb_flag.ROOT))
RUN = ROOT / "data/research/runs/qb001-backup-flag-v1"
MANIFEST = ROOT / "data/research/inputs/nfldata-93a5221-rf001-2006-2023-v1/execution-manifest.json"
GAMES_CSV = (
    ROOT / "data/research/sources/nfldata-93a5221070bcd1733fe3c55abb48e931b3615241/games.csv"
)
saved_run = pytest.mark.skipif(
    not all(p.exists() for p in (RUN / "games.jsonl", MANIFEST, GAMES_CSV)),
    reason="local QB-001 research run not present",
)


@pytest.fixture(scope="module")
def saved():
    from lab.backtest.score_data import load_manifest

    dataset, _ = load_manifest(MANIFEST, require_execution_policy=True)
    rows = [json.loads(line) for line in (RUN / "games.jsonl").read_text().splitlines()]
    return dataset, rows


def max_diff(rows, key, expected):
    """Largest |row[key] - expected[game_id]| over rows."""
    return max(abs(r[key] - expected[r["game_id"]]) for r in rows)


@saved_run
def test_saved_run_no_hook_matches_frozen_elo_2006_2023(saved):
    dataset, reference = saved
    rows = elo_replay.replay(dataset)
    assert [r["game_id"] for r in rows] == [r["game_id"] for r in reference]
    assert {r["season"] for r in rows} == set(range(2006, 2024))
    assert max_diff(rows, "p_elo", {r["game_id"]: r["p_elo"] for r in reference}) < TOL


@saved_run
def test_saved_run_qb001_hook_matches_qb001_2015_2023(saved):
    dataset, reference = saved
    rows = elo_replay.replay(
        dataset,
        elo_replay.qb001_hook(qb_flag.load_starters(GAMES_CSV), 2),
        seasons=qb_flag.TEST_SEASONS,
    )
    test = [r for r in reference if r["season"] in qb_flag.TEST_SEASONS]
    assert [r["game_id"] for r in rows] == [r["game_id"] for r in test]
    k = qb_flag.PENALTIES.index(2)
    assert max_diff(rows, "p", {r["game_id"]: r["p"][k] for r in test}) < TOL
