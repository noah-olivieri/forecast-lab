"""NFL Drivers weekly snapshot: archive full_qb_ridge win probabilities, their inputs and
same-moment Kalshi + Polymarket US quotes (spec docs/superpowers/specs/
2026-10-15-drivers-weekly-snapshot-design.md).

Pure logic, no network and no R: jobs/snapshot_drivers.py runs the R export and the quote
capture and passes their results in. Any failed check raises SnapshotRefused before anything
is written; a snapshot directory is created exclusively and never overwritten.
"""

from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lab.ingest.nflverse import kickoff_dt

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
        meta.get("upcoming_dropped"),
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
