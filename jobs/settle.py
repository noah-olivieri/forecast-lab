"""Settle forecasted NFL games from nflverse final scores (Phase B, minimal auto-settlement).

    settle.py [--now ISO] [--forecasts-dir DIR] [--results-dir DIR]

Every game with a forecast under forecasts/ (the pilot's batch file and the automated per-game
files alike) is checked once per run:
  * Settled when it has no result file yet, the source has both scores, and now >= kickoff + 6h.
    One file per game, results/<season>/<game_id>.csv, created exclusively: an existing result is
    never overwritten or deleted. y = 1 home win, 0 away win, 0.5 tie (RESEARCH_PROTOCOL.md 4).
  * Flagged, never guessed: a game missing from the source, no final score 3+ days after kickoff,
    an existing result whose scores or teams differ from the source, conflicting kickoffs in the
    forecast files, or an unreadable result file.
Ordinary results are written even when something is flagged; the exit code is then 1. A crash
is 2. Written paths go to $GITHUB_OUTPUT as `files` for .github/scripts/push_results.sh.

Kickoff comes from the forecast files (`kickoff_ts`), the time the forecast was made against.
Heavy imports are lazy so the module's top level stays stdlib-only.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORECASTS_DIR = ROOT / "forecasts"
RESULTS_DIR = ROOT / "results"

SETTLE_AFTER = timedelta(hours=6)  # settle no earlier than kickoff + 6h
FLAG_AFTER = timedelta(days=3)  # no final score by kickoff + 3 days is flagged
RESULT_COLUMNS = [
    "game_id", "home_team", "away_team", "home_score", "away_score", "y", "source",
    "fetched_at_utc",
]  # fmt: skip


@dataclass
class Report:
    written: list[Path] = field(default_factory=list)
    already: list[str] = field(default_factory=list)  # settled before, source agrees
    waiting: list[str] = field(default_factory=list)  # too early or no score yet
    flags: list[str] = field(default_factory=list)


def _utc(text: str) -> datetime:
    ts = datetime.fromisoformat(text)
    if ts.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone: {text!r}")
    return ts.astimezone(UTC)


def _stamp(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def forecasted_games(forecasts_dir: Path = FORECASTS_DIR) -> tuple[dict[str, datetime], list[str]]:
    """{game_id: kickoff} from every forecast CSV, and flags for games with conflicting kickoffs."""
    kickoffs: dict[str, set[datetime]] = {}
    for path in sorted(forecasts_dir.rglob("*.csv")):
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row.get("game_id"):
                    kickoffs.setdefault(row["game_id"], set()).add(_utc(row["kickoff_ts"]))
    games, flags = {}, []
    for game_id, seen in sorted(kickoffs.items()):
        if len(seen) == 1:
            games[game_id] = next(iter(seen))
        else:
            times = ", ".join(_stamp(t) for t in sorted(seen))
            flags.append(f"{game_id}: forecast files disagree on kickoff ({times}); not settled")
    return games, flags


def y_value(home_score: int, away_score: int) -> str:
    return "1" if home_score > away_score else "0" if home_score < away_score else "0.5"


def write_result(path: Path, row: dict) -> None:
    """Create `path` exclusively and atomically: FileExistsError if it already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("x", newline="") as f:
            w = csv.DictWriter(f, fieldnames=RESULT_COLUMNS, lineterminator="\n")
            w.writeheader()
            w.writerow({c: row[c] for c in RESULT_COLUMNS})
        os.link(tmp, path)  # fails if `path` exists; never replaces it
    finally:
        tmp.unlink(missing_ok=True)


def existing_result(results_dir: Path, game_id: str) -> list[Path]:
    return sorted(results_dir.glob(f"*/{game_id}.csv")) if results_dir.exists() else []


def _compare(path: Path, src: dict) -> str | None:
    """Why an existing result disagrees with the source, or None."""
    try:
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        old = rows[0]
        old_scores = (int(old["home_score"]), int(old["away_score"]))
        old_teams = (old["home_team"], old["away_team"])
    except (OSError, IndexError, KeyError, ValueError) as exc:
        return f"existing result {path.name} is unreadable ({type(exc).__name__})"
    if len(rows) != 1:
        return f"existing result {path.name} has {len(rows)} rows"
    if old_teams != (src["home_team"], src["away_team"]):
        return (f"existing result teams {old_teams[1]}@{old_teams[0]} differ from the source "
                f"{src['away_team']}@{src['home_team']}")  # fmt: skip
    if src["home_score"] is None or src["away_score"] is None:
        return None  # nothing to compare yet
    new_scores = (int(src["home_score"]), int(src["away_score"]))
    if old_scores != new_scores:
        return (f"existing result scores (home-away) {old_scores[0]}-{old_scores[1]} differ "
                f"from the source {new_scores[0]}-{new_scores[1]}; left untouched")  # fmt: skip
    return None


def settle(
    games: dict[str, datetime],
    source_rows: list[dict],
    now: datetime,
    fetched_at: datetime,
    results_dir: Path,
    source: str,
) -> Report:
    report = Report()
    by_id = {r["game_id"]: r for r in source_rows}
    for game_id, kickoff in sorted(games.items(), key=lambda kv: (kv[1], kv[0])):
        src = by_id.get(game_id)
        if src is None:
            report.flags.append(f"{game_id}: forecasted but not in the source; not settled")
            continue
        existing = existing_result(results_dir, game_id)
        if existing:
            problems = [p for p in (_compare(path, src) for path in existing) if p]
            if len(existing) > 1:
                problems.append(f"{len(existing)} result files exist")
            if problems:
                report.flags.extend(f"{game_id}: {p}" for p in problems)
            else:
                report.already.append(game_id)
            continue
        scored = src["home_score"] is not None and src["away_score"] is not None
        if not scored:
            if now >= kickoff + FLAG_AFTER:
                report.flags.append(
                    f"{game_id}: no final score {now - kickoff} after kickoff "
                    f"{_stamp(kickoff)}; not settled"
                )
            else:
                report.waiting.append(f"{game_id} (no final score yet)")
            continue
        if now < kickoff + SETTLE_AFTER:
            report.waiting.append(f"{game_id} (settles from {_stamp(kickoff + SETTLE_AFTER)})")
            continue
        home, away = int(src["home_score"]), int(src["away_score"])
        path = results_dir / str(src["season"]) / f"{game_id}.csv"
        row = {
            "game_id": game_id,
            "home_team": src["home_team"],
            "away_team": src["away_team"],
            "home_score": home,
            "away_score": away,
            "y": y_value(home, away),
            "source": source,
            "fetched_at_utc": _stamp(fetched_at),
        }
        try:
            write_result(path, row)
        except FileExistsError:
            report.flags.append(f"{game_id}: {path.name} appeared during the run; left untouched")
        else:
            report.written.append(path)
    return report


def load_source(seasons: list[int]) -> tuple[list[dict], str]:
    """nflverse schedules with final scores, the loader the forecasts use."""
    from importlib.metadata import version

    from lab.ingest import nflverse  # lazy: needs nflreadpy/polars

    return nflverse.load_games(seasons), f"nflverse schedules (nflreadpy {version('nflreadpy')})"


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def write_output(env, key: str, value: str) -> None:
    path = env.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def run(
    now: datetime | None,
    forecasts_dir: Path = FORECASTS_DIR,
    results_dir: Path = RESULTS_DIR,
    *,
    load_source_fn=None,
    env=None,
) -> int:
    env = os.environ if env is None else env
    games, flags = forecasted_games(forecasts_dir)
    report = Report(flags=flags)
    if games:
        seasons = sorted({int(game_id[:4]) for game_id in games})
        source_rows, source = (load_source_fn or load_source)(seasons)
        fetched_at = datetime.now(UTC)
        report = settle(games, source_rows, now or fetched_at, fetched_at, results_dir, source)
        report.flags[:0] = flags
    print(f"forecasted={len(games)} settled_now={len(report.written)} "
          f"already={len(report.already)} waiting={len(report.waiting)} "
          f"flags={len(report.flags)}")  # fmt: skip
    for path in report.written:
        print(f"settled: {path.stem} -> {display_path(path)}")
    for game_id in report.already:
        print(f"already settled: {game_id}")
    for line in report.waiting:
        print(f"waiting: {line}")
    for flag in report.flags:
        print(f"::error title=Settlement flag::{flag}")
    write_output(env, "files", ",".join(display_path(p) for p in report.written))
    return 1 if report.flags else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--now", help="ISO timestamp with timezone (tests and dry runs)")
    ap.add_argument("--forecasts-dir", type=Path, default=FORECASTS_DIR)
    ap.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    args = ap.parse_args(argv)
    try:
        now = _utc(args.now) if args.now else None
        return run(now, args.forecasts_dir, args.results_dir)
    except Exception:  # noqa: BLE001  exit 1 is reserved for flags, so a crash is 2
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
