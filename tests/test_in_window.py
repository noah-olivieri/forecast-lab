import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location(
    "in_window", Path(__file__).parent.parent / "jobs" / "in_window.py"
)
iw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iw)

spec = importlib.util.spec_from_file_location(
    "build_kickoffs", Path(__file__).parent.parent / "jobs" / "build_kickoffs.py"
)
bk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bk)

PT = ZoneInfo("America/Los_Angeles")


def pt(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=PT).astimezone(UTC)


def kickoffs_file(tmp_path, *games):
    """games: (away, home, kickoff as Pacific-time datetime args)."""
    rows = [
        {
            "game_id": f"{a}_{h}",
            "away": a,
            "home": h,
            "kickoff_utc": pt(*k).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for a, h, k in games
    ]
    path = tmp_path / "kickoffs.json"
    path.write_text(json.dumps(rows))
    return path


# ---- schedule-driven windows (kickoff - 45 min .. kickoff + 15 min, plus 10 min grace) ----


def test_international_sunday_morning_game(tmp_path):
    f = kickoffs_file(tmp_path, ("PHI", "JAX", (2026, 10, 11, 6, 30)))  # 9:30 AM ET
    for hh, mm in [(5, 45), (6, 30), (6, 45), (6, 55)]:
        assert iw.in_kickoff_window(pt(2026, 10, 11, hh, mm), f), (hh, mm)
    for hh, mm in [(5, 30), (7, 5), (9, 30)]:
        assert not iw.in_kickoff_window(pt(2026, 10, 11, hh, mm), f), (hh, mm)


def test_thursday_night_tb_at_dal(tmp_path):
    f = kickoffs_file(tmp_path, ("TB", "DAL", (2026, 10, 8, 17, 15)))  # 8:15 PM ET
    assert iw.in_kickoff_window(pt(2026, 10, 8, 16, 30), f)  # opens 4:30
    assert iw.in_kickoff_window(pt(2026, 10, 8, 17, 30), f)  # closes 5:30
    assert not iw.in_kickoff_window(pt(2026, 10, 8, 16, 15), f)
    assert not iw.in_kickoff_window(pt(2026, 10, 8, 17, 41), f)


def test_saturday_game_opens_window_on_a_day_the_old_table_never_did(tmp_path):
    f = kickoffs_file(tmp_path, ("A", "B", (2026, 12, 19, 10, 0)))  # Saturday
    assert iw.in_kickoff_window(pt(2026, 12, 19, 10, 0), f)
    assert not iw.in_kickoff_window(pt(2026, 12, 19, 12, 0), f)


def test_window_is_by_absolute_time_across_dst_change(tmp_path):
    f = kickoffs_file(tmp_path, ("A", "B", (2026, 11, 8, 10, 0)))  # first Sunday after DST end
    assert iw.in_kickoff_window(pt(2026, 11, 8, 9, 15), f)
    assert not iw.in_kickoff_window(pt(2026, 11, 8, 9, 0), f)


def test_grace_after_window_end_covers_delayed_runs(tmp_path):
    f = kickoffs_file(tmp_path, ("A", "B", (2026, 10, 11, 10, 0)))
    assert iw.in_kickoff_window(pt(2026, 10, 11, 10, 25), f)
    assert not iw.in_kickoff_window(pt(2026, 10, 11, 10, 26), f)


def test_build_converts_eastern_to_utc_and_sorts():
    assert bk.to_kickoff_utc("2026-10-11", "09:30") == "2026-10-11T13:30:00Z"  # EDT
    assert bk.to_kickoff_utc("2026-11-08", "13:00") == "2026-11-08T18:00:00Z"  # EST
    rows = [
        {
            "game_id": "b",
            "away_team": "X",
            "home_team": "Y",
            "gameday": "2026-10-12",
            "gametime": "20:15",
        },
        {
            "game_id": "a",
            "away_team": "P",
            "home_team": "Q",
            "gameday": "2026-10-08",
            "gametime": "20:15",
        },
        {
            "game_id": "c",
            "away_team": "R",
            "home_team": "S",
            "gameday": "2026-10-20",
            "gametime": None,
        },
    ]
    out = bk.build(rows)
    assert [g["game_id"] for g in out] == ["a", "b"]  # sorted, game with no gametime skipped
    assert out[0]["kickoff_utc"] == "2026-10-09T00:15:00Z"


# ---- fallback to the fixed WINDOWS table ----


def test_missing_file_falls_back_and_warns(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert iw.in_kickoff_window(pt(2026, 10, 11, 12, 45), missing)  # old Sunday slot
    assert not iw.in_kickoff_window(pt(2026, 10, 11, 6, 30), missing)  # old table has no 6:30
    assert "falling back" in capsys.readouterr().err


def test_corrupt_or_empty_file_falls_back(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert iw.in_kickoff_window(pt(2026, 10, 12, 17, 0), bad)  # Monday night fixed window
    bad.write_text("[]")
    assert iw.in_kickoff_window(pt(2026, 10, 12, 17, 0), bad)


# ---- fixed-window table (fallback behavior preserved) ----


def test_fixed_windows_edges_and_dst(tmp_path):
    missing = tmp_path / "nope.json"
    for hh, mm in [(9, 30), (10, 15), (12, 45), (13, 30), (16, 45), (17, 30), (17, 39)]:
        assert iw.in_kickoff_window(pt(2026, 10, 11, hh, mm), missing), (hh, mm)
    for hh, mm in [(9, 15), (10, 30), (12, 30), (17, 41)]:
        assert not iw.in_kickoff_window(pt(2026, 10, 11, hh, mm), missing), (hh, mm)
    # Post-DST Sunday (PST): Pacific wall-clock still decides.
    assert pt(2026, 10, 11, 9, 30).hour == 16 and pt(2026, 11, 8, 9, 30).hour == 17
    assert iw.in_kickoff_window(pt(2026, 11, 8, 9, 30), missing)
    assert not iw.in_kickoff_window(pt(2026, 11, 8, 9, 0), missing)
    # Mon 00:30 UTC == Sun 17:30 PDT
    assert iw.in_kickoff_window(datetime(2026, 10, 12, 0, 30, tzinfo=UTC), missing)


def test_should_run_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(
        iw, "KICKOFFS_PATH", kickoffs_file(tmp_path, ("A", "B", (2026, 10, 11, 10, 0)))
    )
    off = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # Wednesday
    assert iw.should_run("workflow_dispatch", "", off)
    assert iw.should_run("schedule", iw.HOURLY_CRON, off)
    assert not iw.should_run("schedule", iw.WINDOW_CRON, off)
    assert iw.should_run("schedule", iw.WINDOW_CRON, pt(2026, 10, 11, 10, 0))


def test_workflow_crons_match_gate_constants():
    """If collect.yml and the gate disagree, the hourly run is silently window-gated."""
    import yaml

    wf = yaml.safe_load((Path(__file__).parent.parent / ".github/workflows/collect.yml").read_text())
    triggers = wf.get("on", wf.get(True))  # PyYAML parses a bare `on` key as True
    crons = [s["cron"] for s in triggers["schedule"]]
    assert crons == [iw.HOURLY_CRON, iw.WINDOW_CRON]
