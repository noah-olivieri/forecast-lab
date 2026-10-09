"""Offline, receipt-gated NFL score preparation; never loads or fits a model.

Only explicitly audited pre-holdout source bytes are accepted. The receipt is a
human-audited trust boundary, not cryptographic proof of its assertions. Neither
retrospective retrieval nor this extractor proves historical T-24h availability.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
import platform
import re
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import TZPATH, ZoneInfo

from lab.backtest.score_data import ALIAS_VERSION, ALIASES, Dataset, stamp, utc

ROOT = Path(__file__).resolve().parents[3]
INPUT_ROOT = ROOT / "data" / "research" / "inputs"
# A conservative UTC-day guard: earlier than the 2024 regular-season opener.
HOLDOUT_GUARD = datetime(2024, 9, 5, tzinfo=UTC)
FRANCHISES = frozenset(
    [
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
)
RAW_HEADERS = frozenset(
    [
        "game_id",
        "season",
        "week",
        "game_type",
        "gameday",
        "gametime",
        "home_team",
        "away_team",
        "location",
        "home_score",
        "away_score",
    ]
)
SCHEDULE_HEADERS = [
    "game_id",
    "season",
    "week",
    "game_type",
    "kickoff_ts_utc",
    "home_team",
    "away_team",
    "location",
    "revision_id",
    "published_ts",
    "first_seen_ts",
    "fetched_ts",
    "source_hash",
    "availability_evidence",
    "evidence_ref",
]
LABEL_HEADERS = [
    "game_id",
    "season",
    "home_score",
    "away_score",
    "completed",
    "revision_id",
    "published_ts",
    "first_seen_ts",
    "fetched_ts",
    "source_hash",
    "availability_evidence",
    "evidence_ref",
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_local(path, suffix):
    path = Path(path)
    if path.suffix != suffix or any(p.startswith(".") for p in path.parts if p not in {"/", "."}):
        raise ValueError("unsafe local input path")
    if any(parent.is_symlink() for parent in [path, *path.parents]):
        raise ValueError("symlink input forbidden")
    return path


def source_receipt(path):
    receipt_path = safe_local(path, ".json")
    raw = receipt_path.read_bytes()
    receipt = json.loads(raw)
    if (
        receipt.get("schema_version") != 1
        or receipt.get("audited") is not True
        or type(receipt.get("synthetic")) is not bool
    ):
        raise ValueError("explicit audited source receipt and synthetic flag required")
    source = receipt.get("source", {})
    if (
        source.get("repository") != "https://github.com/nflverse/nfldata"
        or source.get("path") != "data/games.csv"
        or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("raw_sha256", "")))
        or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("git_blob_sha1", "")))
        or type(source.get("raw_size")) is not int
        or source["raw_size"] <= 0
    ):
        raise ValueError("immutable audited NFL source version/hash required")
    committed, fetched = utc(source.get("committed_at")), utc(source.get("fetched_ts"))
    if committed >= HOLDOUT_GUARD or fetched < committed:
        raise ValueError("source must precede the locked holdout opener and receipt")
    if (
        type(source.get("maximum_completed_season")) is not int
        or source["maximum_completed_season"] != 2023
    ):
        raise ValueError("audited source must contain only outcomes through 2023 postseason")
    if not source.get("audit_ref"):
        raise ValueError("source audit reference required")
    if receipt["synthetic"] and not source["audit_ref"].startswith("synthetic://"):
        raise ValueError("synthetic audit marker required")
    if not receipt["synthetic"] and (
        source["audit_ref"].startswith("synthetic://") or not receipt.get("completeness_rule_ref")
    ):
        raise ValueError("real source requires independent completeness rule evidence")
    return receipt, raw


def exact_int(value, field):
    if not re.fullmatch(r"\d+", str(value)):
        raise ValueError(f"invalid nonnegative integer {field}")
    return int(value)


def kickoff(day, time):
    """Interpret the documented Eastern local time, rejecting DST gaps/folds."""
    local = datetime.strptime(f"{day} {time}", "%Y-%m-%d %H:%M")  # noqa: DTZ007 -- DST folds/gaps validated below
    zone = ZoneInfo("America/New_York")
    candidates = set()
    for fold in (0, 1):
        aware = local.replace(tzinfo=zone, fold=fold)
        instant = aware.astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == local:
            candidates.add(instant)
    if not candidates:
        raise ValueError("nonexistent America/New_York kickoff time")
    if len(candidates) != 1:
        raise ValueError("ambiguous America/New_York kickoff time")
    return stamp(candidates.pop())


def timezone_provenance():
    try:
        version = importlib.metadata.version("tzdata")
    except importlib.metadata.PackageNotFoundError:
        version = None
    for root in TZPATH:
        file = Path(root) / "America" / "New_York"
        if file.is_file():
            return {
                "zone": "America/New_York",
                "provider": "system-zoneinfo",
                "tzif_sha256": sha(file.read_bytes()),
                "tzdata_dependency_version": version,
            }
    if version:
        from importlib.resources import files

        file = files("tzdata.zoneinfo").joinpath("America", "New_York")
        return {
            "zone": "America/New_York",
            "provider": "tzdata",
            "tzif_sha256": sha(file.read_bytes()),
            "tzdata_dependency_version": version,
        }
    raise ValueError("no auditable America/New_York timezone file")


def cancelled_for(receipt, season):
    entries = receipt.get("expected_exceptions", {}).get(str(season), {}).get("cancelled", [])
    required = {"game_id", "home_team", "away_team", "source_row_present", "reason", "audit_ref"}
    result = {}
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not required <= entry.keys()
            or type(entry["source_row_present"]) is not bool
            or not entry["game_id"]
            or not entry["reason"]
            or not entry["audit_ref"]
        ):
            raise ValueError(
                "cancellation must have independently audited identity and source status"
            )
        if entry["game_id"] in result:
            raise ValueError("duplicate cancellation declaration")
        result[entry["game_id"]] = entry
    if not receipt["synthetic"]:
        if season == 2022:
            if len(result) != 1 or {
                entry[k] for entry in entries for k in ("home_team", "away_team")
            } != {"BUF", "CIN"}:
                raise ValueError("2022 BUF/CIN cancellation declaration required")
        elif result:
            raise ValueError("unregistered cancellation exception")
    return result


def convert(records, receipt, seasons):
    source = receipt["source"]
    revision = "retrospective-" + source["commit"]
    vintage = {
        "revision_id": revision,
        "published_ts": "",
        "first_seen_ts": "",
        "fetched_ts": stamp(utc(source["fetched_ts"])),
        "source_hash": source["raw_sha256"],
        "availability_evidence": "retrospective_fetch",
        "evidence_ref": source["audit_ref"],
    }
    grouped = {
        season: {
            "schedules": [],
            "labels": [],
            "source_rows": [],
            "ledger": [],
            "alias_rows": [],
            "missing_kickoff": [],
            "neutral": [],
            "ties": [],
        }
        for season in seasons
    }
    outside = Counter()
    preseason = Counter()
    cancellations = {season: cancelled_for(receipt, season) for season in seasons}
    ids, physical = set(), set()
    for raw in records:
        season = exact_int(raw["season"], "season")
        # Do not convert or select score fields for unrequested/holdout rows.
        if season not in grouped:
            outside[str(season)] += 1
            continue
        if None in raw or any(value is None for value in raw.values()):
            raise ValueError("malformed CSV row: columns do not match headers")
        if raw["game_type"] == "PRE":
            preseason[str(season)] += 1
            continue
        group = grouped[season]
        gid = raw["game_id"]
        if not gid or gid in ids:
            raise ValueError("missing/duplicate physical game ID")
        ids.add(gid)
        typ = raw["game_type"]
        if typ not in {"REG", "POST", "WC", "DIV", "CON", "SB"}:
            raise ValueError("invalid game_type")
        week = exact_int(raw["week"], "week")
        if week == 0:
            raise ValueError("positive week required")
        home, away = (ALIASES.get(raw[k], raw[k]) for k in ("home_team", "away_team"))
        expected = FRANCHISES - ({"HOU"} if season <= 2001 else set())
        if home not in expected or away not in expected or home == away:
            raise ValueError("invalid canonical franchise identity")
        location = raw["location"]
        if location not in {"Home", "Neutral"}:
            raise ValueError("invalid home/neutral location")
        key = (season, home, away, raw["gameday"], raw["gametime"])
        if key in physical:
            raise ValueError("duplicate physical game under different IDs")
        physical.add(key)
        day = date.fromisoformat(raw["gameday"])
        if day.year not in {season, season + 1}:
            raise ValueError("gameday inconsistent with starting-year season")
        time = kickoff(raw["gameday"], raw["gametime"]) if raw["gametime"] else ""
        cancellation = cancellations[season].get(gid)
        values = [
            None if raw[k] == "" else exact_int(raw[k], k) for k in ("home_score", "away_score")
        ]
        if cancellation:
            if (
                not cancellation["source_row_present"]
                or typ != "REG"
                or (home, away) != (cancellation["home_team"], cancellation["away_team"])
            ):
                raise ValueError("cancellation identity/source status mismatch")
            group["ledger"].append(
                {
                    "game_id": gid,
                    "reason": "cancelled",
                    "audit": cancellation,
                    "raw_score_status": "partial"
                    if any(v is not None for v in values)
                    else "missing",
                }
            )
            values = [None, None]  # Partial cancelled scores are not final labels.
        elif any(v is None for v in values):
            raise ValueError("incomplete scores without audited cancellation")
        if not cancellation and time and utc(time) >= utc(source["committed_at"]):
            raise ValueError("completed outcome cannot postdate immutable source")
        if typ != "REG" and values[0] == values[1]:
            raise ValueError("postseason final tie is invalid")
        if not time:
            group["missing_kickoff"].append(gid)
            group["ledger"].append(
                {
                    "game_id": gid,
                    "reason": "missing_kickoff",
                    "gameday": raw["gameday"],
                    "gametime": raw["gametime"],
                }
            )
        if location == "Neutral":
            group["neutral"].append(gid)
        if values[0] is not None and values[0] == values[1]:
            group["ties"].append(gid)
        if (home, away) != (raw["home_team"], raw["away_team"]):
            group["alias_rows"].append(
                {
                    "game_id": gid,
                    "original_home": raw["home_team"],
                    "original_away": raw["away_team"],
                    "home": home,
                    "away": away,
                }
            )
        group["schedules"].append(
            {
                "game_id": gid,
                "season": season,
                "week": week,
                "game_type": typ,
                "kickoff_ts_utc": time,
                "home_team": home,
                "away_team": away,
                "location": location,
                **vintage,
            }
        )
        group["labels"].append(
            {
                "game_id": gid,
                "season": season,
                "home_score": values[0],
                "away_score": values[1],
                "completed": not cancellation,
                **vintage,
            }
        )
        group["source_rows"].append(raw)
    return grouped, dict(outside), dict(preseason), cancellations


def audit_season(season, group, cancellations, *, synthetic):
    schedules, labels = group["schedules"], group["labels"]
    label_by_id = {r["game_id"]: r for r in labels}
    regular = [r for r in schedules if r["game_type"] == "REG"]
    postseason = [r for r in schedules if r["game_type"] != "REG"]
    omitted = [gid for gid, item in cancellations.items() if not item["source_row_present"]]
    declared_present = {gid for gid, item in cancellations.items() if item["source_row_present"]}
    if declared_present != {r["game_id"] for r in schedules if r["game_id"] in cancellations}:
        raise ValueError("cancellation completeness/status mismatch")
    completed = sum(label_by_id[r["game_id"]]["completed"] for r in regular)
    teams = FRANCHISES - ({"HOU"} if season <= 2001 else set())
    games_per_team = 16 if season <= 2020 else 17
    expected_regular = len(teams) * games_per_team // 2
    expected_post = 11 if season <= 2019 else 13
    appearances = Counter(r[k] for r in regular for k in ("home_team", "away_team"))
    expected_appearances = dict.fromkeys(teams, games_per_team)
    for gid in omitted:
        for key in ("home_team", "away_team"):
            expected_appearances[cancellations[gid][key]] -= 1
    if (
        len(regular) + len(omitted) != expected_regular
        or completed != expected_regular - len(cancellations)
        or len(postseason) != expected_post
        or dict(appearances) != expected_appearances
    ):
        raise ValueError(f"season {season} completeness/appearance counts failed")
    rounds = dict(Counter(row["game_type"] for row in postseason))
    expected_rounds = {"WC": 4 if season <= 2019 else 6, "DIV": 4, "CON": 2, "SB": 1}
    if not synthetic and rounds != expected_rounds:
        raise ValueError(f"season {season} postseason round completeness failed")
    # Reuse the existing loader's public identity/overlap checks, never a model.
    Dataset.from_rows(schedules, labels, "reconstructed_scores")
    for gid in omitted:
        group["ledger"].append(
            {"game_id": gid, "reason": "cancelled_source_omission", "audit": cancellations[gid]}
        )
    return {
        "source_regular_rows": len(regular),
        "regular_scheduled": expected_regular,
        "regular_completed": completed,
        "postseason_completed": len(postseason),
        "regular_appearances": dict(sorted(appearances.items())),
        "cancelled": sorted(cancellations),
        "omitted_cancelled": sorted(omitted),
        "missing_kickoff": group["missing_kickoff"],
        "neutral": group["neutral"],
        "ties": group["ties"],
        "alias_rows": group["alias_rows"],
        "source_fields": sorted(group["source_rows"][0]),
        "field_missingness": {
            field: sum(r.get(field) == "" for r in group["source_rows"])
            for field in group["source_rows"][0]
        },
        "season_isolated": True,
        "counts_complete": True,
        "kickoff_complete": not group["missing_kickoff"],
        "postseason_round_counts": rounds,
        "postseason_rounds_complete": rounds == expected_rounds,
        "final_round_games": [r["game_id"] for r in postseason if r["game_type"] == "SB"],
        "historical_publication_timing_proven": False,
    }


def write_json(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def prepare(raw_path, receipt_path, output_dir, *, seasons=tuple(range(2006, 2024))):
    """Validate an audited local CSV, then write one immutable preparation build.

    Alternative output paths are for local fixtures; the CLI restricts builds to
    ignored data/research/inputs. No source may provide holdout outcome bytes.
    """
    seasons = tuple(seasons)
    if (
        not seasons
        or len(set(seasons)) != len(seasons)
        or any(type(s) is not int or not 1999 <= s <= 2023 for s in seasons)
    ):
        raise ValueError("explicit development seasons only; holdout is locked")
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(output)
    if (
        "forecasts" in output.parts
        or any(p.startswith(".") for p in output.parts if p != "/")
        or any(parent.is_symlink() for parent in [output, *output.parents])
    ):
        raise ValueError("unsafe output path")
    receipt, receipt_bytes = source_receipt(receipt_path)  # Gate before any raw read.
    raw_path = safe_local(raw_path, ".csv")
    raw = raw_path.read_bytes()  # Hash and parse this single snapshot.
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != receipt["source"]["git_blob_sha1"]:
        raise ValueError("raw source Git blob mismatch")
    if len(raw) != receipt["source"]["raw_size"]:
        raise ValueError("raw source size mismatch")
    if sha(raw) != receipt["source"]["raw_sha256"]:
        raise ValueError("raw source hash mismatch")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    if not RAW_HEADERS <= set(reader.fieldnames or []) or len(reader.fieldnames or []) != len(
        set(reader.fieldnames or [])
    ):
        raise ValueError("required unique raw CSV headers missing")
    grouped, outside, preseason, cancellations = convert(reader, receipt, seasons)
    audits = {
        str(s): audit_season(s, grouped[s], cancellations[s], synthetic=receipt["synthetic"])
        for s in sorted(seasons)
    }
    Dataset.from_rows(
        [row for s in seasons for row in grouped[s]["schedules"]],
        [row for s in seasons for row in grouped[s]["labels"]],
        "reconstructed_scores",
    )
    preparation = {
        "source": receipt["source"],
        "raw_sha256": sha(raw),
        "receipt_sha256": sha(receipt_bytes),
        "alias_version": ALIAS_VERSION,
        "extractor_sha256": sha(Path(__file__).read_bytes()),
        "alias_source_sha256": sha(Path(__file__).with_name("score_data.py").read_bytes()),
        "python_version": platform.python_version(),
        "timezone": timezone_provenance(),
        "requested_seasons": sorted(seasons),
        "historical_publication_timing_proven": False,
        "no_fitting_or_tuning": True,
    }
    audit = {
        "seasons": audits,
        "outside_requested_seasons": outside,
        "excluded_preseason_rows": preseason,
        "preparation": preparation,
    }
    manifest = {
        "schema_version": 1,
        "synthetic": receipt["synthetic"],
        "cohort": "reconstructed_scores",
        "revision_clock": "fetched_ts",
        "partitions": [],
        "postseason_rule_metadata": receipt.get("postseason_rule_metadata", {}),
        "preparation": preparation,
        "audit_path": "audit.json",
        "runner_ready": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    try:
        with (output / "receipt.json").open("xb") as stream:
            stream.write(receipt_bytes)
        for season in sorted(seasons):
            group = grouped[season]
            for kind, headers in (("schedules", SCHEDULE_HEADERS), ("labels", LABEL_HEADERS)):
                name = f"{kind}-{season}.csv"
                with (output / name).open("x", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=headers)
                    writer.writeheader()
                    writer.writerows(sorted(group[kind], key=lambda r: r["game_id"]))
                manifest["partitions"].append(
                    {
                        "season": season,
                        "kind": kind,
                        "path": name,
                        "role": "baseline_warmup" if season < 2006 else "development",
                        "sha256": sha((output / name).read_bytes()),
                        "audit": {
                            "season_isolated": True,
                            "kickoff_and_label_coverage_reviewed": True,
                            "kickoff_complete": audits[str(season)]["kickoff_complete"],
                            "audit_path": "audit.json",
                        },
                    }
                )
            write_json(output / f"source-rows-{season}.json", group["source_rows"])
            write_json(output / f"exclusions-{season}.json", group["ledger"])
        write_json(output / "audit.json", audit)
        manifest["audit_sha256"] = sha((output / "audit.json").read_bytes())
        manifest["audit_artifacts"] = [
            {"path": p.name, "sha256": sha(p.read_bytes())}
            for p in sorted(output.iterdir())
            if p.suffix == ".json"
        ]
        rule_ready = all(receipt.get("postseason_rule_metadata", {}).get(str(s)) for s in seasons)
        manifest["runner_ready"] = rule_ready and not any(
            a["omitted_cancelled"] for a in audits.values()
        )
        manifest["readiness_limitations"] = (
            ([] if rule_ready else ["missing reviewed season-specific postseason rule metadata"])
            + (
                ["cancelled scheduled game absent from source; no invented kickoff"]
                if any(a["omitted_cancelled"] for a in audits.values())
                else []
            )
            + (
                ["missing historical kickoff times remain explicit exclusions"]
                if any(a["missing_kickoff"] for a in audits.values())
                else []
            )
            + ["retrospective source does not prove historical T-24h publication"]
        )
        write_json(output / "manifest.json", manifest)
    except BaseException as exc:
        if not (output / "failure.json").exists():
            write_json(
                output / "failure.json", {"status": "failed", "exception_type": type(exc).__name__}
            )
        raise
    return output / "manifest.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--seasons", type=int, nargs="+", default=list(range(2006, 2024)))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.build_id):
        parser.error("build-id must be a new simple directory name")
    print(prepare(args.raw, args.receipt, INPUT_ROOT / args.build_id, seasons=args.seasons))


if __name__ == "__main__":
    main()
