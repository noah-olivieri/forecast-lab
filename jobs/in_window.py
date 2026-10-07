"""Gate for the collector: decide whether this workflow run should capture.

    in_window.py EVENT_NAME CRON_STRING     # writes run=true|false to $GITHUB_OUTPUT

The extra WINDOW_CRON fires every 15 minutes (:07,:22,:37,:52) and this gate decides: a run captures only if
it falls inside a window built from config/kickoffs.json (see build_kickoffs.py), from 45 min
before to 15 min after any kickoff. If that file is missing or unreadable it falls back to the
fixed Pacific-time WINDOWS below and warns. Manual runs and the plain hourly cron always capture.
Stdlib only: it runs before `uv sync`.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Must match the two cron strings in .github/workflows/collect.yml (tests check this). An
# unrecognised schedule string is treated as window-gated.
HOURLY_CRON = "23 * * * *"
WINDOW_CRON = "7,22,37,52 * * * *"
PT = ZoneInfo("America/Los_Angeles")
KICKOFFS_PATH = Path(__file__).resolve().parent.parent / "config" / "kickoffs.json"
BEFORE = timedelta(minutes=45)
AFTER = timedelta(minutes=15)
# Fallback only. Python weekday(): Mon=0 ... Sun=6. Windows are inclusive, Pacific wall-clock.
WINDOWS: dict[int, list[tuple[time, time]]] = {
    3: [(time(16, 30), time(17, 30))],  # Thursday night game
    6: [  # Sunday: early, late-early, and late slots
        (time(9, 30), time(10, 15)),
        (time(12, 45), time(13, 30)),
        (time(16, 45), time(17, 30)),
    ],
    0: [(time(16, 30), time(17, 30))],  # Monday night game
}
# Scheduled runs are routinely delayed by GitHub; a run that starts within this long after a
# window closes still counts, so a late 17:30 slot is not discarded at 17:38.
GRACE = timedelta(minutes=10)


def load_kickoffs(path: Path) -> list[datetime] | None:
    """Kickoff times (aware UTC) from the JSON file, or None if missing/unreadable/empty."""
    try:
        games = json.loads(path.read_text())
        kickoffs = [datetime.fromisoformat(g["kickoff_utc"]).astimezone(UTC) for g in games]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"warning: cannot use {path} ({e!r}); falling back to fixed windows", file=sys.stderr)
        return None
    if not kickoffs:
        print(f"warning: {path} has no games; falling back to fixed windows", file=sys.stderr)
        return None
    return kickoffs


def _in_fixed_windows(now_utc: datetime) -> bool:
    local = now_utc.astimezone(PT)
    for start, end in WINDOWS.get(local.weekday(), []):
        s = datetime.combine(local.date(), start, tzinfo=PT)
        e = datetime.combine(local.date(), end, tzinfo=PT) + GRACE
        if s <= local <= e:
            return True
    return False


def in_kickoff_window(now_utc: datetime, path: Path | None = None) -> bool:
    kickoffs = load_kickoffs(path or KICKOFFS_PATH)
    if kickoffs is None:
        return _in_fixed_windows(now_utc)
    return any(k - BEFORE <= now_utc <= k + AFTER + GRACE for k in kickoffs)


def should_run(event_name: str, cron: str, now_utc: datetime) -> bool:
    if event_name != "schedule" or cron == HOURLY_CRON:
        return True
    return in_kickoff_window(now_utc)


def main(argv: list[str]) -> int:
    event_name, cron = (argv + ["", ""])[:2]
    now = datetime.now(UTC)
    run = should_run(event_name, cron, now)
    print(f"event={event_name!r} cron={cron!r} now_pt={now.astimezone(PT):%a %H:%M} run={run}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"run={'true' if run else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
