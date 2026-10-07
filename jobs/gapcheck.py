"""Fail (exit 1) if the collector missed any recent hour. Usage: gapcheck.py DATA_ROOT [--lookback N|all]"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from lab.config import CONFIG_DIR
from lab.store.snapshots import find_gaps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_root", type=Path)
    ap.add_argument("--lookback", default="3", help="hours to audit, or 'all'")
    args = ap.parse_args()
    cfg = yaml.safe_load((CONFIG_DIR / "markets.yaml").read_text())
    venues = cfg.get("collector", {}).get("venues", ["kalshi"])
    lookback = None if args.lookback == "all" else int(args.lookback)
    gaps = find_gaps(args.data_root, venues, datetime.now(UTC), lookback_hours=lookback)
    if not gaps:
        print("gapcheck: no missing hours")
        return 0
    for venue, hours in gaps.items():
        stamps = ", ".join(f"{h:%Y-%m-%d %H}:00Z" for h in hours)
        print(f"::error title=Missing snapshots ({venue})::{len(hours)} hour(s): {stamps}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
