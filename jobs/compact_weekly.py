"""Compact finished weeks of hourly snapshots. Usage: compact_weekly.py DATA_ROOT"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from lab.store.snapshots import compact_completed_weeks


def main() -> int:
    root = Path(sys.argv[1])
    results = compact_completed_weeks(root, datetime.now(UTC))
    for r in results:
        print(f"compacted {r.weekly_path.name}: {r.rows} rows from {len(r.removed)} hourly file(s)")
    if not results:
        print("compact: nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
