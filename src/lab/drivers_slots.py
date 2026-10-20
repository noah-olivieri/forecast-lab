"""Kickoff slots, snapshot windows, coverage and MISSED for the drivers snapshot bot (spec
docs/superpowers/specs/2026-10-19-drivers-snapshot-automation-design.md).

Stdlib only: jobs/drivers_gate.py imports this before `uv sync`. Shared with
jobs/snapshot_drivers.py so the gate and the snapshot job can't disagree.

  * A slot is a run of games sorted by kickoff; its time S is the earliest kickoff and a game
    joins while kickoff - S < SLOT_WIDTH.
  * Windows [open, close) relative to S: t48 S-48h..S-45h, t24 S-24h..S-21h (timing records),
    t3 S-2h..S-45min (main snapshot). The bot retries inside a window until covered.
  * Main coverage (per game): a `purpose = main` snapshot with created_ts in
    [kickoff - 3h, kickoff) that lists the game. Timing coverage (per slot): a snapshot labelled
    with that slot and timing. Manual snapshots are `main` and never timing records.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

TIMINGS = ("t48", "t24", "t3")
WINDOWS: dict[str, tuple[timedelta, timedelta]] = {  # (open, close) before the slot time S
    "t48": (timedelta(hours=48), timedelta(hours=45)),
    "t24": (timedelta(hours=24), timedelta(hours=21)),
    "t3": (timedelta(hours=2), timedelta(minutes=45)),
}
PURPOSE = {"t48": "timing", "t24": "timing", "t3": "main"}
SLOT_WIDTH = timedelta(minutes=60)  # exclusive: a game 60 min after S starts a new slot
COUNT_WINDOW = timedelta(hours=3)  # DECISIONS.md 2026-10-19 counting rule
RUN_GRACE = timedelta(minutes=45)  # a run that started inside its window may finish this late
MISSED_LOOKBACK = timedelta(hours=6)

# A window is eligible only if it opens at or after its timing's go-live. GO_LIVE_UNSET means
# "not live": nothing eligible, no alerts.
GO_LIVE_UNSET = datetime(2099, 1, 1, tzinfo=UTC)
GO_LIVE: dict[str, datetime] = {"t48": GO_LIVE_UNSET, "t24": GO_LIVE_UNSET, "t3": GO_LIVE_UNSET}


@dataclass(frozen=True)
class Slot:
    start: datetime
    game_ids: tuple[str, ...]

    @property
    def id(self) -> str:
        return f"{self.start.astimezone(UTC):%Y-%m-%dT%H:%MZ}"


@dataclass(frozen=True)
class SnapshotRecord:
    path: Path
    created_ts: datetime
    purpose: str
    timing: str | None
    slot: str | None
    listed: frozenset[str]  # predicted, or excluded for any reason except other_slot


def _aware_utc(text: str) -> datetime:
    ts = datetime.fromisoformat(text)
    if ts.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone: {text!r}")
    return ts.astimezone(UTC)


def load_kickoffs(path: Path) -> dict[str, datetime]:
    return {g["game_id"]: _aware_utc(g["kickoff_utc"]) for g in json.loads(path.read_text())}


def build_slots(kickoffs: dict[str, datetime]) -> list[Slot]:
    slots: list[Slot] = []
    start, ids = None, []
    for game_id, kickoff in sorted(kickoffs.items(), key=lambda kv: (kv[1], kv[0])):
        if start is not None and kickoff - start < SLOT_WIDTH:
            ids.append(game_id)
            continue
        if start is not None:
            slots.append(Slot(start, tuple(ids)))
        start, ids = kickoff, [game_id]
    if start is not None:
        slots.append(Slot(start, tuple(ids)))
    return slots


def find_slot(slots: list[Slot], slot_id: str) -> Slot | None:
    return next((s for s in slots if s.id == slot_id), None)


def window(slot: Slot, timing: str) -> tuple[datetime, datetime]:
    open_before, close_before = WINDOWS[timing]
    return slot.start - open_before, slot.start - close_before


def _game_ids(path: Path, skip_reason: str | None = None) -> set[str]:
    with path.open(newline="") as f:
        return {r["game_id"] for r in csv.DictReader(f)
                if r.get("game_id") and (skip_reason is None or r.get("reason") != skip_reason)}  # fmt: skip


def read_snapshots(root: Path) -> tuple[list[SnapshotRecord], list[str]]:
    """Every snapshot dir under root/<date>/<ts>Z/. Unreadable dirs become warnings, never errors:
    one bad directory must not stop every slot. Old snapshots without labels are `main`."""
    records, warnings = [], []
    if not root.is_dir():
        return records, warnings
    for d in sorted(p for p in root.glob("*/*") if p.is_dir()):
        try:
            meta = json.loads((d / "meta.json").read_text())
            listed = _game_ids(d / "predictions.csv") | _game_ids(d / "excluded.csv", "other_slot")
            records.append(SnapshotRecord(
                path=d, created_ts=_aware_utc(meta["created_ts"]),
                purpose=meta.get("purpose") or "main", timing=meta.get("timing"),
                slot=meta.get("slot"), listed=frozenset(listed),
            ))  # fmt: skip
        except (OSError, ValueError, KeyError) as exc:
            warnings.append(f"unreadable snapshot {d}: {type(exc).__name__}: {exc}")
    return records, warnings


def game_covered_main(game_id: str, kickoff: datetime, records: list[SnapshotRecord]) -> SnapshotRecord | None:  # fmt: skip
    ok = [r for r in records if r.purpose == "main" and game_id in r.listed
          and kickoff - COUNT_WINDOW <= r.created_ts < kickoff]  # fmt: skip
    return min(ok, key=lambda r: r.created_ts, default=None)


def pair_covered(slot: Slot, timing: str, kickoffs: dict[str, datetime], records: list[SnapshotRecord]) -> bool:  # fmt: skip
    if PURPOSE[timing] == "main":
        return all(game_covered_main(g, kickoffs[g], records) is not None for g in slot.game_ids)
    return any(r.slot == slot.id and r.timing == timing for r in records)


def eligible(slot: Slot, timing: str, go_live: dict[str, datetime] | None = None) -> bool:
    return window(slot, timing)[0] >= (GO_LIVE if go_live is None else go_live)[timing]


def pairs_needing_run(
    slots: list[Slot],
    kickoffs: dict[str, datetime],
    records: list[SnapshotRecord],
    now: datetime,
    go_live: dict[str, datetime] | None = None,
) -> list[tuple[Slot, str]]:
    out = []
    for slot in slots:
        for timing in TIMINGS:
            opens, closes = window(slot, timing)
            if (eligible(slot, timing, go_live) and opens <= now < closes
                    and not pair_covered(slot, timing, kickoffs, records)):  # fmt: skip
                out.append((slot, timing))
    return sorted(out, key=lambda p: window(*p)[0])


def missed(
    slots: list[Slot],
    kickoffs: dict[str, datetime],
    records: list[SnapshotRecord],
    now: datetime,
    commit_time: Callable[[Path], datetime | None],
    go_live: dict[str, datetime] | None = None,
) -> list[str]:
    """t3: a game kicked off within the lookback with no counting main snapshot (created within
    3h before kickoff and committed before kickoff; commit time stands in for receipt on main).
    Timing: a pair whose window closed (plus RUN_GRACE) within the lookback, uncovered."""
    out = []
    for slot in slots:
        if eligible(slot, "t3", go_live):
            for g in slot.game_ids:
                k = kickoffs[g]
                if not now - MISSED_LOOKBACK < k <= now:
                    continue
                counted = any(
                    r.purpose == "main" and g in r.listed and k - COUNT_WINDOW <= r.created_ts < k
                    and (ct := commit_time(r.path)) is not None and ct < k
                    for r in records
                )  # fmt: skip
                if not counted:
                    out.append(f"t3 {g} (slot {slot.id}): kickoff {k:%FT%TZ} passed with no "
                               "main snapshot on main within 3h before it")  # fmt: skip
        for timing in ("t48", "t24"):
            deadline = window(slot, timing)[1] + RUN_GRACE
            if (eligible(slot, timing, go_live) and deadline <= now < deadline + MISSED_LOOKBACK
                    and not pair_covered(slot, timing, kickoffs, records)):  # fmt: skip
                out.append(f"{timing} slot {slot.id}: window closed with no timing snapshot")
    return out


def check_created_ts(slot: Slot, timing: str, created_ts: datetime) -> str | None:
    opens, closes = window(slot, timing)
    if created_ts < opens:
        return f"{timing} window for slot {slot.id} opens {opens:%FT%TZ}; capture was {created_ts:%FT%TZ}"  # fmt: skip
    if created_ts >= closes + RUN_GRACE:
        return (f"{timing} window for slot {slot.id} closed {closes:%FT%TZ} (+{RUN_GRACE} grace); "
                f"capture was {created_ts:%FT%TZ}")  # fmt: skip
    return None
