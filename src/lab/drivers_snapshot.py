"""NFL Drivers weekly snapshot: archive full_qb_ridge win probabilities, their inputs and
same-moment Kalshi + Polymarket US quotes (spec docs/superpowers/specs/
2026-10-15-drivers-weekly-snapshot-design.md).

Pure logic, no network and no R: jobs/snapshot_drivers.py runs the R export and the quote
capture and passes their results in. Any failed check raises SnapshotRefused before anything
is written; a snapshot directory is created exclusively and never overwritten.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lab.forecasts import NICKNAMES, _fmt, _tickers, flip_quote
from lab.ingest.nflverse import ET, kickoff_dt

MODEL = "full_qb_ridge"


class SnapshotRefused(RuntimeError):
    """A check failed; nothing may be written."""


def _utc(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


@dataclass(frozen=True)
class Export:
    """What jobs/export_drivers.R wrote: full_qb_ridge rows as strings, plus run metadata."""

    dir: Path
    upcoming: list[dict[str, str]]
    results_created: datetime | None
    schedule_downloaded: datetime | None
    upcoming_dropped: int | None
    code_sha: str | None = None  # git HEAD when run.R ran (nfl-drivers code_state())
    code_dirty: bool | None = None

    @property
    def mode(self) -> str:
        return "full" if (self.dir / "features.csv").exists() else "provenance_only"


def read_export(export_dir: Path) -> Export:
    meta_path, up_path = export_dir / "meta.json", export_dir / "upcoming.csv"
    if not meta_path.exists() or not up_path.exists():
        raise SnapshotRefused(f"R export incomplete in {export_dir}")
    meta = json.loads(meta_path.read_text())
    with up_path.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("model") == MODEL]
    if not rows:
        raise SnapshotRefused(f"no {MODEL} rows in results$upcoming")
    return Export(
        export_dir, rows, _utc(meta.get("created")), _utc(meta.get("schedule_downloaded")),
        meta.get("upcoming_dropped"), meta.get("code_sha"), meta.get("code_dirty"),
    )  # fmt: skip


FRESHNESS = timedelta(hours=6)


def iso_z(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(repo: Path, *args: str) -> str:
    """Raw stdout (not stripped: porcelain lines start with a status column that may be a space)."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def clean_head(repo: Path, allow_prefix: str | None = None) -> str:
    """HEAD's SHA; refuses on any change except untracked files under `allow_prefix`.

    Only untracked (`??`) entries are exempt: a modified, deleted or renamed tracked file is
    refused even under the prefix. `-z` gives unquoted paths, with a rename's source path in
    the next field.
    """
    fields = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
    dirty, i = [], 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        if status[0] in "RC":
            i += 1  # skip the rename/copy source field
        if not (status == "??" and allow_prefix and path.startswith(allow_prefix)):
            dirty.append(path)
    if dirty:
        raise SnapshotRefused(f"{repo}: uncommitted changes: {', '.join(dirty[:5])}")
    return _git(repo, "rev-parse", "HEAD").strip()


def head_commit_time(repo: Path) -> datetime:
    return datetime.fromisoformat(_git(repo, "show", "-s", "--format=%cI", "HEAD").strip())


def check_results_after_commit(results_created: datetime | None, commit_time: datetime) -> None:
    if results_created is None or results_created < commit_time:
        shown = "missing" if results_created is None else iso_z(results_created)
        raise SnapshotRefused(
            f"results$created ({shown}) is before nfl-drivers HEAD's commit time "
            f"{iso_z(commit_time)}; rerun `Rscript run.R` on this commit"
        )


def check_results_code(export: Export, drivers_sha: str) -> None:
    """results.rds must come from the checked-out nfl-drivers commit, run on a clean tree."""
    if export.code_sha is None:
        raise SnapshotRefused("results.rds has no code SHA; rerun `Rscript run.R` on this commit")
    if export.code_sha != drivers_sha:
        raise SnapshotRefused(
            f"results.rds came from nfl-drivers {export.code_sha}, but HEAD is {drivers_sha}"
        )
    if export.code_dirty is not False:
        raise SnapshotRefused("results.rds came from a tree with uncommitted changes (or unknown)")


def check_freshness(export: Export, created_ts: datetime) -> None:
    for name, ts in (
        ("results$created", export.results_created),
        ("schedule_downloaded", export.schedule_downloaded),
    ):
        if ts is None:
            raise SnapshotRefused(f"{name} is missing; freshness cannot be checked")
        if ts > created_ts:
            raise SnapshotRefused(f"{name} {iso_z(ts)} is after capture {iso_z(created_ts)}")
        if created_ts - ts > FRESHNESS:
            raise SnapshotRefused(
                f"{name} {iso_z(ts)} is more than {FRESHNESS} before capture {iso_z(created_ts)}"
            )


def schedule_kickoffs(rows: list[dict[str, str]]) -> dict[str, datetime]:
    """Kickoff per game from the schedule the model used; any missing or bad time refuses."""
    out, bad = {}, []
    for r in rows:
        try:
            out[r["game_id"]] = kickoff_dt(r["gameday"], r["gametime"])
        except (KeyError, TypeError, ValueError):
            bad.append(r.get("game_id") or "?")
    if bad:
        raise SnapshotRefused("no usable kickoff time for: " + ", ".join(bad))
    return out


def effective_kickoffs(
    schedule: dict[str, datetime], config: dict[str, datetime]
) -> tuple[dict[str, datetime], list[dict[str, str]]]:
    """The earlier of the schedule and config/kickoffs.json times, plus every disagreement."""
    eff, disagreements = {}, []
    for game_id, k in schedule.items():
        c = config.get(game_id)
        if c is not None and c != k:
            disagreements.append({"game_id": game_id, "schedule": iso_z(k), "kickoffs_json": iso_z(c)})
        eff[game_id] = k if c is None else min(k, c)
    return eff, disagreements


QUOTE_MAX_AGE = timedelta(minutes=5)
KALSHI, POLYMARKET = "kalshi", "polymarket_us"

PRED_COLUMNS = [
    "game_id", "season", "week", "home_team", "away_team", "kickoff_ts",
    "kickoff_source_disagrees", "game_day_et", "same_day", "created_ts", "minutes_to_kickoff",
    "model", "model_version", "p_home", "pred_margin", "home_qb_projected",
    "away_qb_projected", "status",
    "kalshi_ticker", "kalshi_yes_bid", "kalshi_yes_ask", "kalshi_bid_size", "kalshi_ask_size",
    "kalshi_quote_ts",
    "poly_ticker", "poly_yes_team_raw", "poly_flipped", "poly_yes_bid", "poly_yes_ask",
    "poly_quote_ts",
]  # fmt: skip
EXCLUDED_COLUMNS = ["game_id", "kickoff_ts", "reason"]


def _num(text: str | None) -> float | None:
    return float(text) if text not in (None, "", "NA") else None


def _pick(quotes, venue, ticker, created_ts, game_id, warnings) -> dict | None:
    hits = [q for q in quotes if q["venue"] == venue and q["market_ticker"] == ticker]
    if len(hits) > 1:
        warnings.append(f"{game_id}: {len(hits)} {venue} rows for {ticker}; treated as missing")
        return None
    if not hits:
        return None
    q = hits[0]
    if q["ts_utc"] > created_ts or created_ts - q["ts_utc"] > QUOTE_MAX_AGE:
        warnings.append(f"{game_id}: {venue} quote at {iso_z(q['ts_utc'])} is stale; treated as missing")
        return None
    return q


def _quote_fields(r, kickoff, quotes, created_ts, warnings) -> dict:
    game_id, home, away = r["game_id"], r["home_team"], r["away_team"]
    k_ticker, p_ticker = _tickers(away, home, kickoff.astimezone(ET))
    k = _pick(quotes, KALSHI, k_ticker, created_ts, game_id, warnings)
    p = _pick(quotes, POLYMARKET, p_ticker, created_ts, game_id, warnings)
    flipped = None
    if p is not None:
        yes_team = NICKNAMES.get(p["subtitle"])
        if yes_team not in (home, away):
            warnings.append(f"{p_ticker}: cannot map YES side {p['subtitle']!r}; treated as missing")
            p = None
        else:
            flipped = yes_team == away
    p_bid, p_ask = (None, None) if p is None else (p["yes_bid"], p["yes_ask"])
    if flipped:
        p_bid, p_ask = flip_quote(p_bid, p_ask)
    kv = (lambda key: None) if k is None else (lambda key: k[key])
    return {
        "status": "ok" if k else ("no_kalshi_quote" if p else "no_quotes"),
        "kalshi_ticker": k_ticker, "kalshi_yes_bid": kv("yes_bid"), "kalshi_yes_ask": kv("yes_ask"),
        "kalshi_bid_size": kv("yes_bid_size"), "kalshi_ask_size": kv("yes_ask_size"),
        "kalshi_quote_ts": kv("ts_utc"),
        "poly_ticker": p_ticker, "poly_yes_team_raw": None if p is None else p["subtitle"],
        "poly_flipped": flipped, "poly_yes_bid": p_bid, "poly_yes_ask": p_ask,
        "poly_quote_ts": None if p is None else p["ts_utc"],
    }  # fmt: skip


def build_rows(
    export: Export,
    kickoffs: dict[str, datetime],
    effective: dict[str, datetime],
    quotes: list[dict],
    created_ts: datetime,
    drivers_sha: str,
) -> tuple[list[dict], list[dict], list[str]]:
    """One row per game still before kickoff; started or unpredicted games go to `excluded`."""
    rows, excluded, warnings = [], [], []
    capture_day = created_ts.astimezone(ET).date()
    for r in sorted(export.upcoming, key=lambda r: (kickoffs[r["game_id"]], r["game_id"])):
        game_id, kickoff = r["game_id"], kickoffs[r["game_id"]]
        if effective[game_id] <= created_ts:
            excluded.append({"game_id": game_id, "kickoff_ts": kickoff, "reason": "game_started"})
            continue
        p_home = _num(r.get("pred_win"))
        if p_home is None:
            excluded.append({"game_id": game_id, "kickoff_ts": kickoff, "reason": "no_prediction"})
            continue
        game_day = kickoff.astimezone(ET).date()
        rows.append({
            "game_id": game_id, "season": r["season"], "week": r["week"],
            "home_team": r["home_team"], "away_team": r["away_team"], "kickoff_ts": kickoff,
            "kickoff_source_disagrees": effective[game_id] != kickoff,
            "game_day_et": game_day.isoformat(), "same_day": game_day == capture_day,
            "created_ts": created_ts,
            "minutes_to_kickoff": int((kickoff - created_ts).total_seconds() // 60),
            "model": MODEL, "model_version": f"nfl-drivers@{drivers_sha}", "p_home": p_home,
            "pred_margin": _num(r.get("pred_margin")),
            "home_qb_projected": r.get("home_qb_name") or None,
            "away_qb_projected": r.get("away_qb_name") or None,
            **_quote_fields(r, kickoff, quotes, created_ts, warnings),
        })  # fmt: skip
    return rows, excluded, warnings


def no_quotes_at_all(rows: list[dict]) -> bool:
    return bool(rows) and all(r["status"] == "no_quotes" for r in rows)


def snapshot_dir(out_root: Path, created_ts: datetime) -> Path:
    et_day = created_ts.astimezone(ET).strftime("%Y-%m-%d")
    return out_root / et_day / f"{created_ts.astimezone(UTC):%Y-%m-%dT%H-%M-%S}Z"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("x", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in columns])


def write_snapshot(
    out_root: Path,
    created_ts: datetime,
    rows: list[dict],
    excluded: list[dict],
    meta: dict,
    export: Export,
    schedule_rds: Path | None,
) -> Path:
    """Create the snapshot directory exclusively and write every file into it."""
    d = snapshot_dir(out_root, created_ts)
    d.parent.mkdir(parents=True, exist_ok=True)
    try:
        d.mkdir()
    except FileExistsError:
        raise SnapshotRefused(f"{d} already exists; snapshots are never overwritten") from None
    _write_csv(d / "predictions.csv", PRED_COLUMNS, rows)
    _write_csv(d / "excluded.csv", EXCLUDED_COLUMNS, excluded)
    inputs = d / "inputs"
    inputs.mkdir()
    shutil.copyfile(export.dir / "upcoming.csv", inputs / "upcoming.csv")
    if export.mode == "full":
        shutil.copyfile(export.dir / "features.csv", inputs / "features.csv")
    if schedule_rds is not None and schedule_rds.is_file():
        shutil.copyfile(schedule_rds, inputs / schedule_rds.name)
    (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    return d
