"""Synthetic RF-001 fixtures; these are invented teams and outcomes."""

import importlib
import os
from datetime import UTC, datetime, timedelta

os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name == name:
            raise AssertionError(f"Missing RF-001 behavior: {name}") from exc
        raise


def schedule(gid="g1", kickoff=None, **changes):
    kickoff = kickoff or datetime(2011, 9, 1, 17, tzinfo=UTC)
    row = {
        "game_id": gid,
        "season": kickoff.year,
        "week": 1,
        "game_type": "REG",
        "kickoff_ts_utc": kickoff.isoformat(),
        "home_team": "AAA",
        "away_team": "BBB",
        "location": "Home",
        "revision_id": "s1",
        "published_ts": (kickoff - timedelta(days=7)).isoformat(),
        "fetched_ts": (kickoff - timedelta(days=6)).isoformat(),
        "source_hash": "a" * 64,
        "availability_evidence": "contemporaneous_receipt",
        "evidence_ref": "synthetic://schedule-receipt",
    }
    row.update(changes)
    return row


def label(gid="g1", kickoff=None, **changes):
    kickoff = kickoff or datetime(2011, 9, 1, 17, tzinfo=UTC)
    row = {
        "game_id": gid,
        "season": kickoff.year,
        "revision_id": "l1",
        "home_score": 24,
        "away_score": 17,
        "completed": True,
        "published_ts": (kickoff + timedelta(hours=4)).isoformat(),
        "fetched_ts": (kickoff + timedelta(hours=5)).isoformat(),
        "source_hash": "b" * 64,
        "availability_evidence": "contemporaneous_receipt",
        "evidence_ref": "synthetic://final-score-receipt",
    }
    row.update(changes)
    return row


def history(n=160, start=None):
    start = start or datetime(2011, 1, 1, 17, tzinfo=UTC)
    schedules, labels = [], []
    for i in range(n):
        kickoff = start + timedelta(days=2 * i)
        gid = f"synthetic-{i:04d}"
        schedules.append(
            schedule(
                gid, kickoff, week=i // 8 + 1, home_team=f"T{i % 4}", away_team=f"T{(i + 1) % 4}"
            )
        )
        labels.append(label(gid, kickoff, home_score=20 + 3 * (i % 5), away_score=14 + 2 * (i % 7)))
    return schedules, labels
