"""Invented complete schedules: no network or real outcomes."""

import csv
import hashlib
import json
import os
from datetime import date, timedelta

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
TEAMS = [
    "ARI",
    "ATL",
    "BAL",
    "BUF",
    "CAR",
    "CHI",
    "CIN",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GB",
    "HOU",
    "IND",
    "JAX",
    "KC",
    "LA",
    "LAC",
    "LV",
    "MIA",
    "MIN",
    "NE",
    "NO",
    "NYG",
    "NYJ",
    "PHI",
    "PIT",
    "SEA",
    "SF",
    "TB",
    "TEN",
    "WAS",
]


def rows(season=2023, *, cancelled=False):
    teams = TEAMS.copy()
    result = []
    for week in range(1, 18):
        for index in range(16):
            result.append(
                {
                    "game_id": f"invented-{season}-{week:02d}-{index:02d}",
                    "season": str(season),
                    "week": str(week),
                    "game_type": "REG",
                    "gameday": str(date(season, 9, 3) + timedelta(days=7 * (week - 1))),
                    "gametime": "13:00",
                    "home_team": teams[index],
                    "away_team": teams[-index - 1],
                    "location": "Home",
                    "home_score": "24",
                    "away_score": "17",
                    "home_rest": "7",
                    "away_rest": "7",
                    "stadium": "Invented stadium",
                }
            )
        teams = [teams[0], teams[-1], *teams[1:-1]]
    for index in range(13):
        row = dict(result[0])
        row.update(
            game_id=f"invented-{season}-post-{index}",
            game_type="POST",
            week=str(19 + index),
            gameday=str(date(season + 1, 1, 8) + timedelta(days=7 * index)),
        )
        result.append(row)
    if cancelled:
        result[0].update(home_score="", away_score="")
    return result


def input_files(root, records=None, *, cancelled=False, season=2023):
    root.mkdir(parents=True, exist_ok=True)
    records = records if records is not None else rows(season, cancelled=cancelled)
    raw_path = root / "raw.csv"
    with raw_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=records[0])
        writer.writeheader()
        writer.writerows(records)
    receipt = {
        "schema_version": 1,
        "audited": True,
        "synthetic": True,
        "source": {
            "repository": "https://github.com/nflverse/nfldata",
            "commit": "a" * 40,
            "path": "data/games.csv",
            "committed_at": "2024-04-02T00:00:00Z",
            "maximum_completed_season": 2023,
            "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "raw_size": raw_path.stat().st_size,
            "git_blob_sha1": hashlib.sha1(
                b"blob " + str(raw_path.stat().st_size).encode() + b"\0" + raw_path.read_bytes()
            ).hexdigest(),
            "fetched_ts": "2026-10-08T18:00:00Z",
            "audit_ref": "synthetic://invented-completeness-audit",
        },
        "expected_exceptions": {
            str(season): {
                "cancelled": [
                    {
                        "game_id": records[0]["game_id"],
                        "home_team": records[0]["home_team"],
                        "away_team": records[0]["away_team"],
                        "source_row_present": True,
                        "reason": "invented cancellation",
                        "audit_ref": "synthetic://cancellation",
                    }
                ]
                if cancelled
                else []
            }
        },
        "postseason_rule_metadata": {str(season): "synthetic://reviewed-no-postseason-ties"},
    }
    receipt_path = root / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    return raw_path, receipt_path
