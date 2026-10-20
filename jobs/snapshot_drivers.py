"""Take one NFL Drivers weekly snapshot (spec docs/superpowers/specs/
2026-10-15-drivers-weekly-snapshot-design.md).

    uv run python jobs/snapshot_drivers.py [--drivers ../nfl-drivers] [--rscript Rscript]
        [--slot YYYY-MM-DDTHH:MMZ --timing t48|t24|t3]

Run `Rscript run.R` in nfl-drivers first (within 6 hours). Both repos must be clean. Without
--slot/--timing (manual use) every upcoming game is snapshotted as `purpose = main`. With them
(the drivers workflow, spec 2026-10-19-drivers-snapshot-automation-design.md) only that slot's
games are, labelled with the timing, and the capture must fall inside the window (plus grace,
lab.drivers_slots). Writes
drivers_snapshots/<ET date>/<UTC time>Z/ and prints the paths to commit; it never commits or
pushes. Exit 0 = written, 1 = refused (nothing written), 2 = crash.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path

import yaml

from lab import drivers_slots as sl
from lab import drivers_snapshot as ds
from lab.config import CONFIG_DIR
from lab.forecasts import load_kickoffs

ROOT = Path(__file__).resolve().parent.parent
EXPORT_R = ROOT / "jobs" / "export_drivers.R"
OUT_ROOT = ROOT / "drivers_snapshots"


def run_export(results_rds: Path, out_dir: Path, rscript: str = "Rscript", *, cwd: Path) -> None:
    """Run the exporter from nfl-drivers' directory so its renv (pinned jsonlite) activates."""
    try:
        r = subprocess.run([rscript, str(EXPORT_R), str(results_rds), str(out_dir)],
                           capture_output=True, text=True, check=False, cwd=cwd)  # fmt: skip
    except FileNotFoundError:
        raise ds.SnapshotRefused(f"{rscript} not found") from None
    if r.returncode != 0:
        raise ds.SnapshotRefused(f"R export failed ({r.returncode}): {r.stderr.strip()[-500:]}")


def capture_quotes() -> tuple[list[dict], dict[str, list[str]], datetime]:
    """NFL winner quotes from both venues; a venue that fails records errors, never raises."""
    from lab.ingest import kalshi, polymarket_us  # lazy: network clients

    cfg = yaml.safe_load((CONFIG_DIR / "markets.yaml").read_text())
    ts = datetime.now(UTC).replace(microsecond=0)
    quotes, errors = [], {}
    for venue in (ds.KALSHI, ds.POLYMARKET):
        try:
            if venue == ds.KALSHI:
                api = kalshi.make_api()
                try:
                    rows, errs = kalshi.snapshot(api, {"nfl": cfg["kalshi"]["nfl"]}, ts)
                finally:
                    api.close()
            else:
                api = polymarket_us.make_api()
                try:
                    rows, errs = polymarket_us.snapshot(api, ts)
                finally:
                    api.close()
        except Exception as exc:  # noqa: BLE001  one venue failing must not stop the other
            rows, errs = [], [f"{type(exc).__name__}: {exc}"]
        errors[venue] = errs
        quotes += [r for r in rows if r.get("group") == "nfl" and r.get("kind") == "winner"]
    return quotes, errors, datetime.now(UTC).replace(microsecond=0)


def take_snapshot(drivers, repo, out_root, *, export_fn, capture_fn, config_kickoffs,
                  slot_id=None, timing=None) -> Path:  # fmt: skip
    slot = None
    if slot_id is not None:
        slot = sl.find_slot(sl.build_slots(config_kickoffs), slot_id)
        if slot is None:
            raise ds.SnapshotRefused(f"no slot {slot_id} in config/kickoffs.json")
    labels = {"purpose": sl.PURPOSE[timing] if slot else "main", "timing": timing if slot else None,
              "slot": slot.id if slot else None}  # fmt: skip
    drivers_sha = ds.clean_head(drivers)
    lab_sha = ds.clean_head(repo, allow_prefix="drivers_snapshots/")
    cache = drivers / "data" / "cache"
    with tempfile.TemporaryDirectory() as tmp:
        export_fn(cache / "results.rds", Path(tmp))
        export = ds.read_export(Path(tmp))
        ds.check_results_after_commit(export.results_created, ds.head_commit_time(drivers))
        ds.check_results_code(export, drivers_sha)
        kickoffs = ds.schedule_kickoffs(export.upcoming)
        effective, disagreements = ds.effective_kickoffs(kickoffs, config_kickoffs)
        quotes, capture_errors, created_ts = capture_fn()
        if slot is not None and (reason := sl.check_created_ts(slot, timing, created_ts)):
            raise ds.SnapshotRefused(reason)
        ds.check_freshness(export, created_ts)
        rows, excluded, warnings = ds.build_rows(
            export, kickoffs, effective, quotes, created_ts, drivers_sha,
            disagree={d["game_id"] for d in disagreements},
            slot_games=frozenset(slot.game_ids) if slot else None, labels=labels,
            config_kickoffs=config_kickoffs,
        )  # fmt: skip
        season = max(int(r["season"]) for r in export.upcoming)
        schedule_rds = cache / f"schedules_{season}.rds"
        hashed = ("results.rds", schedule_rds.name, f"pbp_{season}.rds")
        sha256 = {name: ds.sha256_file(cache / name) for name in hashed}
        sha256["renv.lock"] = ds.sha256_file(drivers / "renv.lock")
        meta = {
            "created_ts": ds.iso_z(created_ts), "mode": export.mode, **labels,
            "nfl_drivers_sha": drivers_sha, "forecast_lab_sha": lab_sha,
            "results_created": ds.iso_z(export.results_created),
            "schedule_downloaded": ds.iso_z(export.schedule_downloaded),
            "upcoming_dropped": export.upcoming_dropped,
            "n_games": len(rows), "n_excluded": len(excluded),
            "kickoff_disagreements": disagreements, "capture_errors": capture_errors,
            "r_version": export.r_version, "r_packages": export.r_packages,
            "sha256": sha256,
        }  # fmt: skip
        path = ds.write_snapshot(out_root, created_ts, rows, excluded, meta, export, schedule_rds)
    for w in warnings:
        print(f"::warning title=Snapshot input::{w}")
    for d in disagreements:
        print(f"::warning title=Kickoff disagreement::{d}")
    if ds.no_quotes_at_all(rows):
        print("::error title=No quotes::no game has a Kalshi or Polymarket quote; "
              f"probabilities were saved anyway (capture errors: {capture_errors})")  # fmt: skip
    if export.upcoming_dropped:
        print(f"::warning title=Upcoming dropped::nfl-drivers dropped {export.upcoming_dropped} "
              "forecast-week games with incomplete features")  # fmt: skip
    return path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--drivers", type=Path, default=ROOT.parent / "nfl-drivers")
    ap.add_argument("--rscript", default="Rscript")
    ap.add_argument("--slot", help="slot id YYYY-MM-DDTHH:MMZ (drivers workflow)")
    ap.add_argument("--timing", choices=sl.TIMINGS, help="t48, t24 or t3 (drivers workflow)")
    args = ap.parse_args(argv)
    if (args.slot is None) != (args.timing is None):
        ap.error("--slot and --timing go together")
    drivers = args.drivers.resolve()
    try:
        path = take_snapshot(
            drivers, ROOT, OUT_ROOT,
            export_fn=lambda rds, out: run_export(rds, out, args.rscript, cwd=drivers),
            capture_fn=capture_quotes, config_kickoffs=load_kickoffs(),
            slot_id=args.slot, timing=args.timing,
        )  # fmt: skip
    except ds.SnapshotRefused as exc:
        print(f"::error title=Snapshot refused::{exc}")
        return 1
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2
    files = sorted(p for p in path.rglob("*") if p.is_file())
    print(f"wrote {path.relative_to(ROOT)}")
    print("commit with:\n  git add -- " + " ".join(str(p.relative_to(ROOT)) for p in files))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
