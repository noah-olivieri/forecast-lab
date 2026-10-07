import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location(
    "in_window", Path(__file__).parent.parent / "jobs" / "in_window.py"
)
iw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iw)

PT = ZoneInfo("America/Los_Angeles")


def pt(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=PT).astimezone(UTC)


# 2026-10-11 is a Sunday (PDT); 2026-11-08 is a Sunday after the Nov 1 DST end (PST).
def test_sunday_windows_edges_inclusive():
    for hh, mm in [(9, 30), (10, 15), (12, 45), (13, 30), (16, 45), (17, 30)]:
        assert iw.in_kickoff_window(pt(2026, 10, 11, hh, mm)), (hh, mm)


def test_sunday_outside_windows():
    for hh, mm in [(9, 15), (10, 30), (11, 30), (12, 30), (14, 0), (16, 30), (18, 0)]:
        assert not iw.in_kickoff_window(pt(2026, 10, 11, hh, mm)), (hh, mm)


def test_grace_after_window_end_covers_delayed_runs():
    assert iw.in_kickoff_window(pt(2026, 10, 11, 17, 39))
    assert not iw.in_kickoff_window(pt(2026, 10, 11, 17, 41))


def test_thursday_and_monday_night():
    assert iw.in_kickoff_window(pt(2026, 10, 8, 16, 30))  # Thu
    assert iw.in_kickoff_window(pt(2026, 10, 12, 17, 0))  # Mon
    assert not iw.in_kickoff_window(pt(2026, 10, 8, 16, 0))
    assert not iw.in_kickoff_window(pt(2026, 10, 12, 18, 0))


def test_other_days_never():
    for d in (7, 9, 10, 13):  # Wed, Fri, Sat, Tue
        assert not iw.in_kickoff_window(pt(2026, 10, d, 17, 0))


def test_windows_follow_pacific_time_across_dst_change():
    # Same Pacific wall-clock time maps to different UTC before/after Nov 1.
    assert pt(2026, 10, 11, 9, 30).hour == 16 and pt(2026, 11, 8, 9, 30).hour == 17
    assert iw.in_kickoff_window(pt(2026, 11, 8, 9, 30))
    assert not iw.in_kickoff_window(pt(2026, 11, 8, 9, 0))


def test_utc_sunday_evening_is_pacific_sunday_not_monday():
    # Mon 00:30 UTC == Sun 17:30 PDT: must count as Sunday's last window.
    assert iw.in_kickoff_window(datetime(2026, 10, 12, 0, 30, tzinfo=UTC))


def test_should_run_rules():
    off = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # Wednesday
    assert iw.should_run("workflow_dispatch", "", off)
    assert iw.should_run("schedule", iw.HOURLY_CRON, off)
    assert not iw.should_run("schedule", "*/15 16-21,23 * * 0", off)
    assert iw.should_run("schedule", "*/15 16-21,23 * * 0", pt(2026, 10, 11, 12, 45))
