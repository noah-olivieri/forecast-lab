"""Capture one snapshot of every tracked market and write one Parquet file per venue.

    snapshot_markets.py DATA_ROOT [--venues kalshi,polymarket_us] [--dry-run]

NFL series are fetched before econ ones. A failing series or venue is reported as a GitHub
warning and the rest still gets written; the job fails only if nothing at all was captured.
`--dry-run` fetches and prints the tracked-market list but writes nothing.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

from lab.config import CONFIG_DIR
from lab.ingest import kalshi, polymarket_us
from lab.ingest.common import write_snapshot
from lab.store.snapshots import HOURLY_DIR, hourly_name


def _load_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "markets.yaml").read_text())


def capture(venue: str, cfg: dict, ts: datetime) -> tuple[list[dict], list[str]]:
    if venue == "kalshi":
        api = kalshi.make_api()
        try:
            series = {"nfl": cfg["kalshi"]["nfl"], "econ": cfg["kalshi"]["econ"]}
            return kalshi.snapshot(api, series, ts)
        finally:
            api.close()
    if venue == "polymarket_us":
        api = polymarket_us.make_api()
        try:
            regex = cfg.get("polymarket_us", {}).get(
                "econ_title_regex", polymarket_us.DEFAULT_ECON_TITLE_RE
            )
            return polymarket_us.snapshot(api, ts, econ_title_re=regex)
        finally:
            api.close()
    raise SystemExit(f"unknown venue: {venue}")


def summarize(rows: list[dict]) -> str:
    c = Counter((r["venue"], r["group"], r["series"], r["kind"]) for r in rows)
    ev = Counter(
        (r["venue"], r["group"], r["series"]) for r in {r["event_ticker"]: r for r in rows}.values()
    )
    lines = [f"{'venue':14} {'group':5} {'series':16} {'kind':7} {'events':>6} {'markets':>7}"]
    for (v, g, s, k), n in sorted(c.items(), key=lambda kv: (kv[0][1] != "nfl", kv[0])):
        lines.append(f"{v:14} {g:5} {s:16} {k:7} {ev[(v, g, s)]:>6} {n:>7}")
    return "\n".join(lines)


def dry_run_report(rows: list[dict], ts: datetime, n_games: int = 5) -> str:
    """Counts by venue/group/kind plus the next kickoffs (Polymarket's gameStartTime is real
    kickoff; Kalshi's event_time is ~3h after it, so kickoffs come from Polymarket)."""
    c = Counter((r["venue"], r["group"], r["kind"]) for r in rows)
    lines = [f"{'venue':14} {'group':5} {'kind':7} {'markets':>7}"]
    lines += [f"{v:14} {g:5} {k:7} {n:>7}" for (v, g, k), n in sorted(c.items())]
    lines.append(f"{'total':28} {len(rows):>7}")
    games = {}
    for r in rows:
        if r["venue"] == "polymarket_us" and r["group"] == "nfl" and r["event_time"] >= ts:
            games[r["event_ticker"]] = r["event_time"]
    lines.append("\nnearest NFL games (kickoff UTC, Polymarket markets per game):")
    for slug, t in sorted(games.items(), key=lambda kv: kv[1])[:n_games]:
        teams = slug.split("-")[1:3]
        pm = sum(1 for r in rows if r["event_ticker"] == slug)
        lines.append(
            f"  {t:%a %Y-%m-%d %H:%M} {'@'.join(x.upper() for x in teams):10} polymarket_us={pm}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_root", type=Path)
    ap.add_argument("--venues", help="comma list; default from config/markets.yaml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = _load_config()
    venues = args.venues.split(",") if args.venues else cfg["collector"]["venues"]
    ts = datetime.now(UTC).replace(microsecond=0)
    all_rows: list[dict] = []
    for venue in venues:
        try:
            rows, errors = capture(venue, cfg, ts)
        except Exception as exc:  # noqa: BLE001
            rows, errors = [], [f"{venue}: {type(exc).__name__}: {exc}"]
        for e in errors:
            print(f"::warning title=Snapshot partial failure::{e}")
        if not rows:
            print(f"::warning title=No rows::{venue} returned no markets")
            continue
        all_rows.extend(rows)
        if not args.dry_run:
            path = args.data_root / HOURLY_DIR / hourly_name(ts, venue)
            n = write_snapshot(rows, path)
            print(f"wrote {path} ({n} rows, {path.stat().st_size / 1024:.0f} KiB)")
    print(summarize(all_rows))
    if args.dry_run:
        print("\n" + dry_run_report(all_rows, ts))
    if not all_rows:
        print("::error title=Snapshot failed::no markets captured from any venue")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
