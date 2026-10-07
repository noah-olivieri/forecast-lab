"""Write config/kickoffs.json from the real NFL schedule: [{game_id, away, home, kickoff_utc}].

    build_kickoffs.py [SEASON]       # default: season in progress

nflverse gives `gameday` + `gametime` as US/Eastern wall-clock. jobs/in_window.py reads the
output to open 15-minute collection windows around each kickoff. Games with no gametime yet
are skipped; the weekly workflow reruns this so flex-scheduling changes get picked up.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import nflreadpy

from lab.ingest.nflverse import to_kickoff_utc

OUT = Path(__file__).resolve().parent.parent / "config" / "kickoffs.json"


def build(rows: list[dict]) -> list[dict]:
    games = [
        {
            "game_id": r["game_id"],
            "away": r["away_team"],
            "home": r["home_team"],
            "kickoff_utc": to_kickoff_utc(r["gameday"], r["gametime"]),
        }
        for r in rows
        if r.get("gameday") and r.get("gametime")
    ]
    return sorted(games, key=lambda g: (g["kickoff_utc"], g["game_id"]))


def current_season() -> int:
    """NFL season in progress: Jan-Feb playoffs still belong to the previous year's season."""
    now = datetime.now(UTC)
    return now.year if now.month >= 3 else now.year - 1


def main(argv: list[str]) -> int:
    season = int(argv[0]) if argv else current_season()
    games = build(nflreadpy.load_schedules(season).to_dicts())
    if not games:
        print(f"no games with a gametime for season {season}; leaving {OUT} untouched")
        return 1
    OUT.write_text(json.dumps(games, indent=1) + "\n")
    print(f"wrote {len(games)} games to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
