"""Layout, gap detection, and weekly compaction for market snapshot files.

Snapshots live on the `data` branch, not on `main`:
    snapshots/hourly/<YYYYMMDD>T<HHMM>Z_<venue>.parquet   one file per collector run
    snapshots/weekly/<ISOYEAR>-W<WW>_<venue>.parquet      compacted, one per week and venue
The timestamp in an hourly name is the capture time in UTC, not the scheduled time.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

HOURLY_DIR = Path("snapshots/hourly")
WEEKLY_DIR = Path("snapshots/weekly")
_HOURLY_RE = re.compile(r"^(\d{8}T\d{4})Z_([a-z0-9_]+)\.parquet$")


def hourly_name(ts: datetime, venue: str) -> str:
    return f"{ts.astimezone(UTC):%Y%m%dT%H%M}Z_{venue}.parquet"


def parse_hourly(path: Path | str) -> tuple[datetime, str] | None:
    m = _HOURLY_RE.match(Path(path).name)
    if not m:
        return None
    ts = datetime.strptime(m.group(1), "%Y%m%dT%H%M").replace(tzinfo=UTC)
    return ts, m.group(2)


def list_hourly(data_root: Path) -> list[tuple[datetime, str, Path]]:
    out = []
    for p in sorted((data_root / HOURLY_DIR).glob("*.parquet")):
        parsed = parse_hourly(p)
        if parsed:
            out.append((parsed[0], parsed[1], p))
    return out


def _floor_hour(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def find_gaps(
    data_root: Path,
    venues: list[str],
    now: datetime,
    *,
    grace: timedelta = timedelta(minutes=15),
    lookback_hours: int | None = 3,
) -> dict[str, list[datetime]]:
    """Return, per venue, the UTC hours with no snapshot.

    Only hours that ended at least `grace` ago are judged, and only from a venue's first
    snapshot onward, so a fresh install does not alarm. `lookback_hours=None` audits the
    whole range; a small window keeps one gap from alerting on every later run.
    A venue with no snapshots at all is not a gap (collection has not started).
    """
    files = list_hourly(data_root)
    last_judged = _floor_hour(now - grace) - timedelta(hours=1)  # last hour that has ended
    gaps: dict[str, list[datetime]] = {}
    for venue in venues:
        stamps = [ts for ts, v, _ in files if v == venue]
        if not stamps:
            continue
        have = {_floor_hour(ts) for ts in stamps}
        start = _floor_hour(min(stamps))
        if lookback_hours is not None:
            start = max(start, last_judged - timedelta(hours=lookback_hours - 1))
        missing, h = [], start
        while h <= last_judged:
            if h not in have:
                missing.append(h)
            h += timedelta(hours=1)
        if missing:
            gaps[venue] = missing
    return gaps


@dataclass
class CompactResult:
    iso_year: int
    iso_week: int
    venue: str
    rows: int
    weekly_path: Path
    removed: list[Path]


def _week_end(ts: datetime) -> datetime:
    iso = ts.isocalendar()
    monday = _floor_hour(ts).replace(hour=0) - timedelta(days=iso.weekday - 1)
    return monday + timedelta(days=7)


def compact_completed_weeks(
    data_root: Path, now: datetime, *, settle: timedelta = timedelta(hours=6)
) -> list[CompactResult]:
    """Merge each finished ISO week of hourly files into one Parquet file per venue.

    A week is finished `settle` after its end (late runs can still land). Row counts are
    checked before any hourly file is deleted, and an existing weekly file is merged in,
    so a re-run after a partial failure is safe.
    """
    groups: dict[tuple[int, int, str], list[Path]] = defaultdict(list)
    for ts, venue, path in list_hourly(data_root):
        if now >= _week_end(ts) + settle:
            iso = ts.isocalendar()
            groups[(iso.year, iso.week, venue)].append(path)

    results = []
    weekly_dir = data_root / WEEKLY_DIR
    for (year, week, venue), paths in sorted(groups.items()):
        weekly_dir.mkdir(parents=True, exist_ok=True)
        target = weekly_dir / f"{year}-W{week:02d}_{venue}.parquet"
        sources = ([target] if target.exists() else []) + sorted(paths)
        tmp = target.with_suffix(".tmp")
        con = duckdb.connect()
        try:
            listing = "[" + ", ".join(f"'{s.as_posix()}'" for s in sources) + "]"
            expected = sum(
                con.execute(f"SELECT count(*) FROM read_parquet('{s.as_posix()}')").fetchone()[0]
                for s in sources
            )
            con.execute(
                f"COPY (SELECT * FROM read_parquet({listing}, union_by_name=true)) "
                f"TO '{tmp.as_posix()}' (FORMAT parquet, COMPRESSION zstd)"
            )
            got = con.execute(f"SELECT count(*) FROM read_parquet('{tmp.as_posix()}')").fetchone()[0]
        finally:
            con.close()
        if got != expected:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"compaction row mismatch for {target.name}: {got} != {expected}")
        tmp.replace(target)
        for p in paths:
            p.unlink()
        results.append(CompactResult(year, week, venue, got, target, paths))
    return results
