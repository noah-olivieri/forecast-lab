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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
