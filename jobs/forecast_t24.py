"""Automated T-24h NFL forecasts, the rule pre-registered in RESEARCH_PROTOCOL.md.

    forecast_t24.py gate [--now ISO]                       # stdlib only; runs before `uv sync`
    forecast_t24.py run --game-ids A,B [--now ISO]         # builds and writes one CSV per game

The rule, all times UTC and fixed in advance:
  * Window for a game: [kickoff - 24h, kickoff - 21h).
  * The first successful run inside the window makes the forecast. No forecast by the close is
    MISSED.
  * Eligible: every game in config/kickoffs.json with kickoff >= GO_LIVE + 24h. Nobody picks
    games: `gate` derives the list from the clock, kickoffs.json and forecasts/, and `run`
    re-derives it and refuses any game that is not open.

`gate` exit codes: 0 = fine, 1 = at least one eligible game was missed (an `::error` per game),
2 = crash. It writes `game_ids` and `missed` to $GITHUB_OUTPUT before exiting.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KICKOFFS_PATH = ROOT / "config" / "kickoffs.json"
FORECASTS_DIR = ROOT / "forecasts"
DATA_ROOT = ROOT / "data-branch"

# Must equal the schedule cron in .github/workflows/forecast.yml (tests check this).
FORECAST_CRON = "11,26,41,56 * * * *"

# Automation goes live at the TB@DAL kickoff: the manual pilot ends, automation begins. Games
# with kickoff >= GO_LIVE + 24h are eligible. GO_LIVE_UNSET is the "not configured" sentinel: if
# GO_LIVE ever equals it, nothing is eligible and the gate warns.
GO_LIVE_UNSET = datetime(2099, 1, 1, tzinfo=UTC)
GO_LIVE = datetime(2026, 10, 9, 0, 15, tzinfo=UTC)

WINDOW_OPEN = timedelta(hours=24)  # window opens this long before kickoff
WINDOW_CLOSE = timedelta(hours=21)  # and closes (exclusive) this long before kickoff
MISSED_LOOKBACK = timedelta(hours=6)  # alert on windows that closed within this long
SNAPSHOT_MAX_AGE = timedelta(minutes=30)  # a staler Kalshi snapshot fails that run (retried)


@dataclass(frozen=True)
class Selection:
    open_ids: list[str] = field(default_factory=list)
    missed_ids: list[str] = field(default_factory=list)


def _aware_utc(text: str) -> datetime:
    ts = datetime.fromisoformat(text)
    if ts.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone: {text!r}")
    return ts.astimezone(UTC)


def load_kickoffs(path: Path = KICKOFFS_PATH) -> dict[str, datetime]:
    return {g["game_id"]: _aware_utc(g["kickoff_utc"]) for g in json.loads(path.read_text())}


def forecast_game_ids(forecasts_dir: Path = FORECASTS_DIR) -> set[str]:
    """Every game that already has a forecast file: new per-game names and legacy batch rows."""
    found: set[str] = set()
    for path in forecasts_dir.rglob("*.csv"):
        if path.name.startswith("nfl-t24_"):
            found.add(path.name.removeprefix("nfl-t24_").removesuffix(".csv"))
        with path.open(newline="") as f:
            found.update(r["game_id"] for r in csv.DictReader(f) if r.get("game_id"))
    return found


def effective_go_live(go_live: datetime | None = None) -> datetime:
    return GO_LIVE if go_live is None else go_live


def is_eligible(kickoff: datetime, go_live: datetime | None = None) -> bool:
    return kickoff >= effective_go_live(go_live) + WINDOW_OPEN


def is_open(kickoff: datetime, now: datetime) -> bool:
    return kickoff - WINDOW_OPEN <= now < kickoff - WINDOW_CLOSE


def select(
    kickoffs: dict[str, datetime],
    now: datetime,
    forecasts_dir: Path = FORECASTS_DIR,
    go_live: datetime | None = None,
) -> Selection:
    """Games whose window is open with no forecast, and recently closed ones with none."""
    have = forecast_game_ids(forecasts_dir)
    open_ids, missed_ids = [], []
    for game_id, kickoff in sorted(kickoffs.items(), key=lambda kv: (kv[1], kv[0])):
        if game_id in have or not is_eligible(kickoff, go_live):
            continue
        close = kickoff - WINDOW_CLOSE
        if is_open(kickoff, now):
            open_ids.append(game_id)
        elif close <= now < close + MISSED_LOOKBACK:
            missed_ids.append(game_id)
    return Selection(open_ids, missed_ids)


def write_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def gate(now: datetime, kickoffs_path: Path, forecasts_dir: Path) -> int:
    if effective_go_live() >= GO_LIVE_UNSET:
        print("::warning title=GO_LIVE unset::GO_LIVE is still the placeholder; nothing eligible")
    kickoffs = load_kickoffs(kickoffs_path)
    sel = select(kickoffs, now, forecasts_dir)
    print(f"now={now:%FT%TZ} games={len(kickoffs)} open={len(sel.open_ids)} "
          f"missed={len(sel.missed_ids)}")  # fmt: skip
    for game_id in sel.open_ids:
        print(f"open: {game_id} (kickoff {kickoffs[game_id]:%FT%TZ})")
    for game_id in sel.missed_ids:
        close = kickoffs[game_id] - WINDOW_CLOSE
        print(f"::error title=T-24h forecast MISSED::{game_id}: window closed {close:%FT%TZ} "
              f"with no forecast")  # fmt: skip
    write_output("game_ids", ",".join(sel.open_ids))
    write_output("missed", "true" if sel.missed_ids else "false")
    return 1 if sel.missed_ids else 0


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def refusal(game_id: str, kickoffs: dict[str, datetime], now: datetime) -> str | None:
    """Why `run` must not forecast this game right now, or None. Re-derives the gate's rule."""
    kickoff = kickoffs.get(game_id)
    if kickoff is None:
        return "not in kickoffs.json"
    if not is_eligible(kickoff):
        return f"not eligible: kickoff {kickoff:%FT%TZ} is before GO_LIVE + 24h"
    if not is_open(kickoff, now):
        return (f"window [{kickoff - WINDOW_OPEN:%FT%TZ}, {kickoff - WINDOW_CLOSE:%FT%TZ}) "
                f"is not open at {now:%FT%TZ}")  # fmt: skip
    return None


def run_games(
    game_ids: list[str],
    now: datetime | None,
    kickoffs_path: Path = KICKOFFS_PATH,
    forecasts_dir: Path = FORECASTS_DIR,
    data_root: Path = DATA_ROOT,
    *,
    load_games_fn=None,
    git_sha_fn=None,
    env=None,
) -> int:
    """Write one forecast CSV per game; every game that can be written is, then 1 if any failed.

    `now=None` reads the clock: once before loading nflverse (window check) and again right
    before building rows (that instant is `as_of` and `created_ts`). Heavy imports are lazy so
    the module's top level stays stdlib-only for `gate`.
    """
    env = os.environ if env is None else env
    clock = (lambda: now) if now is not None else (lambda: datetime.now(UTC))
    kickoffs = load_kickoffs(kickoffs_path)
    outcome: dict[str, tuple[str, str]] = {}  # game_id -> (written|skipped|failed, detail)
    written: list[Path] = []

    have = forecast_game_ids(forecasts_dir)
    todo = []
    for game_id in game_ids:
        why = refusal(game_id, kickoffs, clock())
        if why:
            outcome[game_id] = ("failed", why)
        elif game_id in have:
            outcome[game_id] = ("skipped", "already has a forecast")
        else:
            todo.append(game_id)

    if todo:
        from lab import forecasts as fc  # lazy: needs duckdb/polars
        from lab.ingest import nflverse
        from lab.store.db import connect, init_schema

        con = connect(":memory:")
        init_schema(con)
        nflverse.upsert_games(con, (load_games_fn or nflverse.load_games)())
        created_ts = clock()
        for game_id in list(todo):  # the window may have closed while nflverse was loading
            why = refusal(game_id, kickoffs, created_ts)
            if why:
                outcome[game_id] = ("failed", why)
                todo.remove(game_id)
        git_sha = (git_sha_fn or fc.current_git_sha)()
        rows, warnings, failures = fc.build_rows(
            con, data_root, todo, created_ts, created_ts, git_sha, kickoffs,
            horizon="t24", run_id=env.get("GITHUB_RUN_ID", ""),
            run_attempt=env.get("GITHUB_RUN_ATTEMPT", ""),
        )  # fmt: skip
        for w in warnings:
            print(f"::warning title=Forecast input::{w}")
        for failure in failures:
            outcome[failure.game_id] = ("failed", failure.reason)
        for game_id in todo:
            if game_id in outcome:
                continue
            game = [r for r in rows if r["game_id"] == game_id]
            age = created_ts - game[0]["as_of_ts"] if game else None
            if not game:
                outcome[game_id] = ("failed", "no model produced a probability")
            elif age > SNAPSHOT_MAX_AGE:
                reason = f"Kalshi snapshot is {age} old (max {SNAPSHOT_MAX_AGE})"
                outcome[game_id] = ("failed", reason)
            elif game_id in forecast_game_ids(forecasts_dir):  # re-check right before writing
                outcome[game_id] = ("skipped", "forecast appeared since the first check")
            else:
                try:
                    path = fc.write_game(game, forecasts_dir)
                except FileExistsError:
                    outcome[game_id] = ("skipped", "file already exists; left untouched")
                except fc.ForecastError as exc:
                    outcome[game_id] = ("failed", str(exc))
                else:
                    outcome[game_id] = ("written", display_path(path))
                    written.append(path)

    for game_id in game_ids:
        status, detail = outcome[game_id]
        line = f"{status}: {game_id}" + (f" -> {detail}" if status == "written" else f" ({detail})")
        print(f"::error title=Forecast failed::{line}" if status == "failed" else line)
    write_output("files", ",".join(display_path(p) for p in written))
    return 1 if any(s == "failed" for s, _ in outcome.values()) else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("gate", "run"):
        p = sub.add_parser(name)
        p.add_argument("--now", help="ISO timestamp with timezone (tests and dry runs)")
        p.add_argument("--kickoffs", type=Path, default=KICKOFFS_PATH)
        p.add_argument("--forecasts-dir", type=Path, default=FORECASTS_DIR)
        if name == "run":
            p.add_argument("--game-ids", default="", help="comma list from the gate's output")
            p.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = ap.parse_args(argv)
    try:
        now = _aware_utc(args.now) if args.now else None
        if args.cmd == "gate":
            return gate(now or datetime.now(UTC), args.kickoffs, args.forecasts_dir)
        ids = [g for g in args.game_ids.split(",") if g]
        return run_games(ids, now, args.kickoffs, args.forecasts_dir, args.data_root)
    except Exception:  # noqa: BLE001  exit 1 is reserved for "missed", so a crash is 2
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
