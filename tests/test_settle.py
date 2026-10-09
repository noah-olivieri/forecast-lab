"""Settlement job (jobs/settle.py) on synthetic data, plus its workflow, push script and the
results/ append-only guard. No network: the score source is injected and git runs against local
bare repos in tmp dirs."""

import csv
import importlib.util
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from test_forecast_workflows import clone, commit_file, git, guard, history, make_remote, workflow
from test_forecast_workflows import uses as workflow_uses

REPO = Path(__file__).parent.parent
PUSH = REPO / ".github" / "scripts" / "push_results.sh"

spec = importlib.util.spec_from_file_location("settle", REPO / "jobs" / "settle.py")
st = importlib.util.module_from_spec(spec)
sys.modules["settle"] = st
spec.loader.exec_module(st)

KICKOFF = datetime(2026, 10, 11, 17, 0, tzinfo=UTC)
LATE = KICKOFF + timedelta(hours=6)
FETCHED = datetime(2026, 10, 12, 15, 37, tzinfo=UTC)
SOURCE = "synthetic-test-source"

# The real pilot file's header and one row, so the legacy batch format stays readable.
PILOT_HEADER = (
    "model,model_version,git_sha,venue,market_ticker,game_id,yes_team,prices_flipped,as_of_ts,"
    "p_yes,created_ts,kickoff_ts,market_yes_bid,market_yes_ask,snapshot_ts"
)
PILOT_ROW = (
    "elo,elo-538-default-v0,0227f801386e9607d68e59af1f40379745be5720,kalshi,"
    "KXNFLGAME-26OCT08TBDAL-DAL,2026_05_TB_DAL,DAL,False,2026-10-08T00:05:49Z,"
    "0.6776761161584652,2026-10-08T00:08:28Z,2026-10-09T00:15:00Z,0.79,0.8,2026-10-08T00:05:49Z"
)


def forecast(dirpath, game_id, kickoff=KICKOFF, name=None):
    """A per-game forecast file in the automated format (two rows, as with two venues)."""
    path = Path(dirpath) / "2026-10-11" / (name or f"nfl-t24_{game_id}.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    k = kickoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [f"elo,{game_id},{k}", f"home_rate,{game_id},{k}"]
    path.write_text("model,game_id,kickoff_ts\n" + "\n".join(rows) + "\n")
    return path


def game(game_id, home_score, away_score, season=2026):
    away, home = game_id.split("_")[2:4]
    return {
        "game_id": game_id,
        "season": season,
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
    }


def settle(tmp_path, source_rows, now=LATE):
    forecasts, results = tmp_path / "forecasts", tmp_path / "results"
    games, flags = st.forecasted_games(forecasts)
    report = st.settle(games, source_rows, now, FETCHED, results, SOURCE)
    report.flags[:0] = flags
    return report


def read(path):
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))


# ---- settling ----------------------------------------------------------------------------------


def test_home_win_is_y_1_with_all_columns(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    report = settle(tmp_path, [game("2026_06_NYG_DAL", 27, 20)])
    path = tmp_path / "results" / "2026" / "2026_06_NYG_DAL.csv"
    assert report.written == [path] and report.flags == []
    assert path.read_text().splitlines()[0] == ",".join(st.RESULT_COLUMNS)
    assert read(path) == [
        {
            "game_id": "2026_06_NYG_DAL",
            "home_team": "DAL",
            "away_team": "NYG",
            "home_score": "27",
            "away_score": "20",
            "y": "1",
            "source": SOURCE,
            "fetched_at_utc": "2026-10-12T15:37:00Z",
        }
    ]


def test_away_win_is_y_0(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    settle(tmp_path, [game("2026_06_NYG_DAL", 10, 13)])
    assert read(tmp_path / "results/2026/2026_06_NYG_DAL.csv")[0]["y"] == "0"


def test_tie_is_y_one_half(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    settle(tmp_path, [game("2026_06_NYG_DAL", 17, 17)])
    assert read(tmp_path / "results/2026/2026_06_NYG_DAL.csv")[0]["y"] == "0.5"


def test_too_early_is_not_settled_and_not_flagged(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    report = settle(tmp_path, [game("2026_06_NYG_DAL", 27, 20)], now=LATE - timedelta(seconds=1))
    assert report.written == [] and report.flags == []
    assert not (tmp_path / "results").exists()
    assert settle(tmp_path, [game("2026_06_NYG_DAL", 27, 20)], now=LATE).written  # boundary


def test_no_score_yet_waits_without_a_flag_before_three_days(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    now = KICKOFF + timedelta(days=3) - timedelta(seconds=1)
    report = settle(tmp_path, [game("2026_06_NYG_DAL", None, None)], now=now)
    assert report.written == [] and report.flags == []


def test_no_score_three_days_after_kickoff_is_flagged(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    now = KICKOFF + timedelta(days=3)
    report = settle(tmp_path, [game("2026_06_NYG_DAL", 24, None)], now=now)
    assert report.written == []
    assert len(report.flags) == 1 and "2026_06_NYG_DAL" in report.flags[0]
    assert "no final score" in report.flags[0]


def test_already_settled_is_skipped_and_untouched(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    settle(tmp_path, [game("2026_06_NYG_DAL", 27, 20)])
    path = tmp_path / "results/2026/2026_06_NYG_DAL.csv"
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    report = settle(tmp_path, [game("2026_06_NYG_DAL", 27, 20)], now=LATE + timedelta(days=1))
    assert report.written == [] and report.flags == []
    assert report.already == ["2026_06_NYG_DAL"]
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime


def test_existing_result_with_different_scores_is_flagged_and_untouched(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    settle(tmp_path, [game("2026_06_NYG_DAL", 27, 20)])
    path = tmp_path / "results/2026/2026_06_NYG_DAL.csv"
    before = path.read_bytes()
    report = settle(tmp_path, [game("2026_06_NYG_DAL", 27, 23)])
    assert report.written == []
    assert len(report.flags) == 1 and "differ" in report.flags[0]
    assert "27-20" in report.flags[0] and "27-23" in report.flags[0]
    assert path.read_bytes() == before


def test_missing_game_is_flagged_while_ordinary_results_are_still_written(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    forecast(tmp_path / "forecasts", "2026_06_KC_BUF")
    report = settle(tmp_path, [game("2026_06_NYG_DAL", 27, 20)])
    assert [p.name for p in report.written] == ["2026_06_NYG_DAL.csv"]
    assert len(report.flags) == 1 and "2026_06_KC_BUF" in report.flags[0]
    assert "not in the source" in report.flags[0]


def test_write_result_refuses_to_overwrite(tmp_path):
    path = tmp_path / "results/2026/G.csv"
    st.write_result(path, {c: "x" for c in st.RESULT_COLUMNS})
    with pytest.raises(FileExistsError):
        st.write_result(path, {c: "y" for c in st.RESULT_COLUMNS})
    assert read(path) == [{c: "x" for c in st.RESULT_COLUMNS}]
    assert sorted(p.name for p in path.parent.iterdir()) == ["G.csv"]  # no temp file left


def test_result_in_another_season_folder_counts_as_settled(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    st.write_result(
        tmp_path / "results/2025/2026_06_NYG_DAL.csv",
        {**{c: "" for c in st.RESULT_COLUMNS}, "home_score": "27", "away_score": "20",
         "home_team": "DAL", "away_team": "NYG", "game_id": "2026_06_NYG_DAL"},
    )  # fmt: skip
    report = settle(tmp_path, [game("2026_06_NYG_DAL", 27, 20)])
    assert report.written == [] and report.flags == []
    assert not (tmp_path / "results/2026").exists()


# ---- forecast files ----------------------------------------------------------------------------


def test_pilot_batch_file_and_per_game_files_are_both_read(tmp_path):
    pilot = tmp_path / "forecasts" / "2026-10-08" / "nfl_2026-10-08T00-05Z.csv"
    pilot.parent.mkdir(parents=True)
    pilot.write_text(PILOT_HEADER + "\n" + PILOT_ROW + "\n" + PILOT_ROW + "\n")
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    games, flags = st.forecasted_games(tmp_path / "forecasts")
    assert flags == []
    assert games == {
        "2026_05_TB_DAL": datetime(2026, 10, 9, 0, 15, tzinfo=UTC),
        "2026_06_NYG_DAL": KICKOFF,
    }


def test_pilot_settles_from_its_file(tmp_path):
    pilot = tmp_path / "forecasts" / "2026-10-08" / "nfl_2026-10-08T00-05Z.csv"
    pilot.parent.mkdir(parents=True)
    pilot.write_text(PILOT_HEADER + "\n" + PILOT_ROW + "\n")
    report = settle(
        tmp_path, [game("2026_05_TB_DAL", 16, 24)], now=datetime(2026, 10, 9, 12, tzinfo=UTC)
    )
    assert read(report.written[0])[0] | {"source": "", "fetched_at_utc": ""} == {
        "game_id": "2026_05_TB_DAL", "home_team": "DAL", "away_team": "TB",
        "home_score": "16", "away_score": "24", "y": "0", "source": "", "fetched_at_utc": "",
    }  # fmt: skip


def test_conflicting_kickoffs_for_one_game_are_flagged_not_guessed(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL", KICKOFF + timedelta(hours=3), "other.csv")
    games, flags = st.forecasted_games(tmp_path / "forecasts")
    assert "2026_06_NYG_DAL" not in games
    assert len(flags) == 1 and "kickoff" in flags[0]


# ---- command line ------------------------------------------------------------------------------


def run_main(tmp_path, source_rows, now=LATE):
    out = tmp_path / "github_output"
    out.touch()
    code = st.run(
        now,
        tmp_path / "forecasts",
        tmp_path / "results",
        load_source_fn=lambda seasons: (source_rows, SOURCE),
        env={"GITHUB_OUTPUT": str(out)},
    )
    return code, out.read_text()


def test_run_exits_zero_and_lists_written_files(tmp_path, capsys):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    code, output = run_main(tmp_path, [game("2026_06_NYG_DAL", 27, 20)])
    assert code == 0
    assert output.strip() == f"files={tmp_path / 'results/2026/2026_06_NYG_DAL.csv'}"
    assert "settled: 2026_06_NYG_DAL" in capsys.readouterr().out


def test_run_exits_nonzero_after_writing_when_anything_is_flagged(tmp_path, capsys):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    forecast(tmp_path / "forecasts", "2026_06_KC_BUF")
    code, output = run_main(tmp_path, [game("2026_06_NYG_DAL", 27, 20)])
    assert code == 1
    assert "2026_06_NYG_DAL.csv" in output
    assert (tmp_path / "results/2026/2026_06_NYG_DAL.csv").exists()
    printed = capsys.readouterr().out
    assert "::error title=Settlement flag::2026_06_KC_BUF" in printed


def test_run_loads_only_the_forecasted_seasons(tmp_path):
    forecast(tmp_path / "forecasts", "2026_06_NYG_DAL")
    seen = []
    st.run(LATE, tmp_path / "forecasts", tmp_path / "results",
           load_source_fn=lambda seasons: (seen.append(seasons) or [], SOURCE), env={})  # fmt: skip
    assert seen == [[2026]]


def test_run_with_no_forecasts_does_nothing(tmp_path):
    (tmp_path / "forecasts").mkdir()
    called = []
    code = st.run(LATE, tmp_path / "forecasts", tmp_path / "results",
                  load_source_fn=lambda s: called.append(s), env={})  # fmt: skip
    assert code == 0 and called == []


# ---- settle.yml ----------------------------------------------------------------------------------


def test_settle_runs_daily_and_manually_without_inputs():
    wf = workflow("settle.yml")
    assert [s["cron"] for s in wf["on"]["schedule"]] == ["37 15 * * *"]
    assert not (wf["on"]["workflow_dispatch"] or {}).get("inputs")
    text = (REPO / ".github/workflows/settle.yml").read_text()
    assert "inputs." not in text
    assert "push_results.sh" in text and "push_forecasts.sh" not in text
    assert wf["concurrency"] == {"group": "settle", "cancel-in-progress": False}


def test_settle_uses_only_action_versions_from_collect_yml():
    assert workflow_uses("settle.yml") <= workflow_uses("collect.yml")


# ---- push_results.sh ---------------------------------------------------------------------------

NEW = "results/2026/2026_06_NYG_DAL.csv"


def push(repo, tmp_path, *paths):
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
           "GITHUB_SERVER_URL": "https://gh", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "9"}  # fmt: skip
    return subprocess.run(
        ["bash", str(PUSH), *paths], cwd=repo, env=env, capture_output=True, text=True, check=False
    )


def test_push_results_pushes_only_the_named_new_result(tmp_path):
    bare = make_remote(tmp_path)
    repo = clone(tmp_path, bare, "w")
    (repo / NEW).parent.mkdir(parents=True)
    (repo / NEW).write_text("game_id\n2026_06_NYG_DAL\n")
    (repo / "README.md").write_text("modified, must not be committed\n")
    r = push(repo, tmp_path, NEW)
    assert r.returncode == 0, r.stderr
    assert git(bare, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
    assert git(repo, "show", "--name-only", "--format=", "HEAD").splitlines() == [NEW]
    assert git(repo, "log", "-1", "--format=%an") == "github-actions[bot]"
    assert git(repo, "log", "-1", "--format=%s") == "settle: 2026_06_NYG_DAL"


def test_push_results_refuses_forecasts_other_paths_and_existing_results(tmp_path):
    bare = make_remote(tmp_path)
    repo = clone(tmp_path, bare, "w")
    commit_file(repo, "forecasts/2026-10-11/nfl-t24_G.csv", "model\n")
    assert push(repo, tmp_path, "forecasts/2026-10-11/nfl-t24_G.csv").returncode == 1
    assert push(repo, tmp_path, "README.md").returncode == 1
    commit_file(repo, NEW, "game_id\nA\n")
    (repo / NEW).write_text("game_id\nCHANGED\n")
    assert push(repo, tmp_path, NEW).returncode == 1
    assert git(bare, "log", "--format=%s", "main").splitlines() == ["c"]  # nothing was pushed


def test_push_results_retries_and_aborts_if_another_run_added_the_file(tmp_path):
    bare = make_remote(tmp_path)
    repo, other = clone(tmp_path, bare, "w"), clone(tmp_path, bare, "o")
    commit_file(other, NEW, "game_id\nOTHER_RUN\n")
    git(other, "push", "-q", "origin", "main")
    (repo / NEW).parent.mkdir(parents=True)
    (repo / NEW).write_text("game_id\nMINE\n")
    assert push(repo, tmp_path, NEW).returncode == 1
    assert git(bare, "show", f"main:{NEW}") == "game_id\nOTHER_RUN"


# ---- append-only guard now covers results/ -------------------------------------------------------


def test_guard_allows_new_results(tmp_path):
    repo, base = history(tmp_path)
    commit_file(repo, "results/2026/a.csv", "1\n")
    assert guard(repo, base, "HEAD").returncode == 0


def test_guard_fails_when_a_result_is_modified_or_deleted(tmp_path):
    repo, _ = history(tmp_path)
    commit_file(repo, "results/2026/a.csv", "1\n")
    base = git(repo, "rev-parse", "HEAD")
    commit_file(repo, "results/2026/a.csv", "2\n", "edit")
    r = guard(repo, base, "HEAD")
    assert r.returncode == 1 and "results/2026/a.csv" in r.stdout
    (tmp_path / "second").mkdir()
    repo2, _ = history(tmp_path / "second")
    commit_file(repo2, "results/2026/a.csv", "1\n")
    base2 = git(repo2, "rev-parse", "HEAD")
    git(repo2, "rm", "-q", "results/2026/a.csv")
    git(repo2, "commit", "-q", "-m", "delete")
    assert guard(repo2, base2, "HEAD").returncode == 1
