"""Gate for the automated NFL Drivers snapshots (spec docs/superpowers/specs/
2026-10-19-drivers-snapshot-automation-design.md). Stdlib only; runs before `uv sync`.

    drivers_gate.py gate [--now ISO]                          # which (slot, timing) pairs to run
    drivers_gate.py check --slot ID --timing T [--now ISO]    # is this pair still worth running?

The rule lives in src/lab/drivers_slots.py: slots from config/kickoffs.json, windows t48/t24/t3,
coverage from drivers_snapshots/ on main. Nobody picks slots: workflow_dispatch has no inputs,
`gate` derives the pairs from the clock, and `check` re-derives them when a queued job starts.

`gate` writes `pairs` (JSON list of {"slot", "timing"}) and `missed` to $GITHUB_OUTPUT and exits
0 = fine, 1 = something was MISSED (an `::error` per miss), 2 = crash. `check` writes `run`
(true/false) and exits 0 unless it crashes (2).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from lab import drivers_slots as sl  # stdlib-only module; no install needed

KICKOFFS_PATH = ROOT / "config" / "kickoffs.json"
SNAPSHOTS_DIR = ROOT / "drivers_snapshots"

# Must equal the schedule cron in .github/workflows/drivers.yml (tests check this). Odd minutes
# that avoid collect (:07/:22/:37/:52, :23), forecast (:11/:26/:41/:56) and kickoffs (10:17).
DRIVERS_CRON = "4,19,34,49 * * * *"


def write_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def git_commit_time(path: Path, repo: Path = ROOT) -> datetime | None:
    """Commit time of the commit that added <path>/meta.json; None if it isn't committed."""
    r = subprocess.run(
        ["git", "log", "--diff-filter=A", "-1", "--format=%cI", "--", str(path / "meta.json")],
        cwd=repo, capture_output=True, text=True, check=False,
    )  # fmt: skip
    text = r.stdout.strip()
    return datetime.fromisoformat(text).astimezone(UTC) if r.returncode == 0 and text else None


def _load(kickoffs_path: Path, snapshots_dir: Path):
    kickoffs = sl.load_kickoffs(kickoffs_path)
    records, warnings = sl.read_snapshots(snapshots_dir)
    for w in warnings:
        print(f"::warning title=Unreadable snapshot::{w}")
    return kickoffs, sl.build_slots(kickoffs), records


def gate(now: datetime, kickoffs_path: Path, snapshots_dir: Path) -> int:
    if sl.GO_LIVE["t3"] >= sl.GO_LIVE_UNSET:
        print("::warning title=GO_LIVE unset::GO_LIVE['t3'] is the placeholder; nothing eligible")
    kickoffs, slots, records = _load(kickoffs_path, snapshots_dir)
    pairs = sl.pairs_needing_run(slots, kickoffs, records, now)
    misses = sl.missed(slots, kickoffs, records, now, git_commit_time)
    print(f"now={now:%FT%TZ} games={len(kickoffs)} slots={len(slots)} snapshots={len(records)} "
          f"pairs={len(pairs)} missed={len(misses)}")  # fmt: skip
    for slot, timing in pairs:
        print(f"run: {timing} slot {slot.id} ({', '.join(slot.game_ids)})")
    for msg in misses:
        print(f"::error title=Drivers snapshot MISSED::{msg}")
    write_output("pairs", json.dumps([{"slot": s.id, "timing": t} for s, t in pairs]))
    write_output("missed", "true" if misses else "false")
    return 1 if misses else 0


def check(slot_id: str, timing: str, now: datetime, kickoffs_path: Path, snapshots_dir: Path) -> int:  # fmt: skip
    kickoffs, slots, records = _load(kickoffs_path, snapshots_dir)
    slot = sl.find_slot(slots, slot_id)
    if slot is None:
        print(f"::warning title=Unknown slot::{slot_id} is no longer a slot in kickoffs.json")
        write_output("run", "false")
        return 0
    run = (slot, timing) in sl.pairs_needing_run(slots, kickoffs, records, now)
    print(f"{timing} slot {slot_id}: {'run' if run else 'nothing to do (closed or covered)'}")
    write_output("run", "true" if run else "false")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("gate", "check"):
        p = sub.add_parser(name)
        p.add_argument("--now", help=argparse.SUPPRESS)
        p.add_argument("--kickoffs", type=Path, default=KICKOFFS_PATH, help=argparse.SUPPRESS)
        p.add_argument("--snapshots", type=Path, default=SNAPSHOTS_DIR, help=argparse.SUPPRESS)
        if name == "check":
            p.add_argument("--slot", required=True)
            p.add_argument("--timing", required=True, choices=sl.TIMINGS)
    args = ap.parse_args(argv)
    try:
        now = sl._aware_utc(args.now) if args.now else datetime.now(UTC)
        if args.cmd == "gate":
            return gate(now, args.kickoffs, args.snapshots)
        return check(args.slot, args.timing, now, args.kickoffs, args.snapshots)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
