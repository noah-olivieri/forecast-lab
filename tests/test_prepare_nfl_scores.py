"""Preparation contracts against synthetic, season-complete local CSVs."""

import hashlib
import importlib
import json
import os
from pathlib import Path

import pytest

from nfl_preparation_fixtures import input_files, rows

os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def preparation():
    try:
        return importlib.import_module("lab.backtest.prepare_nfl_scores")
    except ModuleNotFoundError as exc:
        raise AssertionError("Missing offline preparation behavior") from exc


def build(tmp_path, records=None, **kwargs):
    raw, receipt = input_files(tmp_path / "input", records, **kwargs)
    result = preparation().prepare(
        raw, receipt, tmp_path / "output", seasons=[kwargs.get("season", 2023)]
    )
    return result, raw, receipt


def test_complete_partition_is_compatible_scoreless_and_retrospective(tmp_path):
    manifest_path, raw, _ = build(tmp_path)
    from lab.backtest.score_data import load_manifest

    dataset, manifest = load_manifest(manifest_path)
    assert len(dataset.targets()) == 285
    assert len(dataset.labels) == 285
    assert manifest["cohort"] == "reconstructed_scores"
    assert manifest["synthetic"] is True
    game = dataset.targets()[0]
    assert game.kickoff.isoformat() == "2023-09-03T17:00:00+00:00"
    assert game.vintage.published_ts is None and game.vintage.first_seen_ts is None
    assert game.vintage.availability_evidence == "retrospective_fetch"
    assert dataset.eligible(game.as_of) == []
    assert manifest["preparation"]["raw_sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert manifest["preparation"]["alias_version"] == "franchise-v1"
    schedule = (manifest_path.parent / "schedules-2023.csv").read_text().splitlines()[0]
    assert "home_score" not in schedule and "away_score" not in schedule
    audit = json.loads((manifest_path.parent / "audit.json").read_text())
    assert audit["seasons"]["2023"]["regular_completed"] == 272
    assert audit["seasons"]["2023"]["postseason_completed"] == 13
    assert audit["seasons"]["2023"]["regular_appearances"] == dict.fromkeys(
        __import__("nfl_preparation_fixtures").TEAMS, 17
    )
    assert manifest["preparation"]["timezone"]["zone"] == "America/New_York"
    assert manifest["preparation"]["extractor_sha256"]


@pytest.mark.parametrize(
    "changes",
    [
        {"commit": "main"},
        {"committed_at": "2024-09-06T00:00:00Z"},
        {"maximum_completed_season": 2024},
        {"raw_sha256": "bad"},
        {"path": ".env"},
        {"fetched_ts": "2026-10-08"},
    ],
)
def test_source_gate_precedes_raw_read(tmp_path, monkeypatch, changes):
    raw, receipt = input_files(tmp_path / "input")
    doc = json.loads(receipt.read_text())
    doc["source"].update(changes)
    receipt.write_text(json.dumps(doc))
    original = Path.read_bytes

    def protected(path):
        if path == raw:
            pytest.fail("Unsafe source was opened before the receipt gate")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", protected)
    with pytest.raises(ValueError):
        preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2023])
    assert not (tmp_path / "output").exists()


def test_holdout_season_is_rejected_before_source_open(tmp_path, monkeypatch):
    raw, receipt = input_files(tmp_path / "input")
    monkeypatch.setattr(Path, "read_bytes", lambda path: pytest.fail("raw bytes opened"))
    with pytest.raises(ValueError, match="holdout|season"):
        preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2024])


def test_source_hash_is_the_exact_bytes_parsed(tmp_path, monkeypatch):
    raw, receipt = input_files(tmp_path / "input")
    original = Path.read_bytes

    def replacing(path):
        content = original(path)
        if path == raw:
            raw.write_bytes(content.replace(b"13:00", b"19:00"))
        return content

    monkeypatch.setattr(Path, "read_bytes", replacing)
    path = preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2023])
    assert "17:00:00.000000Z" in (path.parent / "schedules-2023.csv").read_text()


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("drop", "completeness"),
        ("duplicate", "duplicate"),
        ("negative", "score"),
        ("decimal", "score"),
        ("post_tie", "postseason.*tie"),
        ("unknown_team", "franchise"),
        ("overlap", "overlap"),
        ("missing_score", "incomplete|cancel"),
    ],
)
def test_invalid_inputs_fail_without_publishing_manifest(tmp_path, mutation, match):
    records = rows()
    if mutation == "drop":
        records.pop()
    elif mutation == "duplicate":
        row = dict(records[0])
        row["game_id"] = "different-id"
        records.append(row)
    elif mutation == "negative":
        records[0]["home_score"] = "-1"
    elif mutation == "decimal":
        records[0]["away_score"] = "17.5"
    elif mutation == "post_tie":
        records[-1]["away_score"] = "24"
    elif mutation == "unknown_team":
        records[0]["home_team"] = "XX"
    elif mutation == "overlap":
        records[16]["gameday"] = records[0]["gameday"]
        records[16]["gametime"] = "14:00"
    elif mutation == "missing_score":
        records[0]["home_score"] = ""
    with pytest.raises(ValueError, match=match):
        build(tmp_path, records)
    assert not (tmp_path / "output" / "manifest.json").exists()


def test_cancellation_is_retained_and_missing_time_is_quarantined(tmp_path):
    records = rows(2022, cancelled=True)
    records[1]["gametime"] = ""
    path, _, _ = build(tmp_path, records, season=2022, cancelled=True)
    from lab.backtest.score_data import load_manifest

    dataset, _ = load_manifest(path)
    assert len(dataset.labels) == 285
    assert dataset.evaluation_label(records[0]["game_id"]) is None
    assert dataset.exclusions[0]["game_id"] == records[1]["game_id"]
    audit = json.loads((path.parent / "audit.json").read_text())["seasons"]["2022"]
    assert audit["regular_scheduled"] == 272 and audit["regular_completed"] == 271
    assert audit["cancelled"] == [records[0]["game_id"]]
    assert audit["missing_kickoff"] == [records[1]["game_id"]]


@pytest.mark.parametrize("day,time", [("2023-03-12", "02:30"), ("2023-11-05", "01:30")])
def test_ambiguous_or_nonexistent_eastern_time_fails(tmp_path, day, time):
    records = rows()
    records[0].update(gameday=day, gametime=time)
    with pytest.raises(ValueError, match="ambiguous|nonexistent"):
        build(tmp_path, records)


def test_out_of_scope_seasons_are_gated_before_score_conversion(tmp_path):
    records = rows()
    extra = dict(records[0])
    extra.update(
        game_id="locked-unplayed",
        season="2024",
        home_score="NOT-AN-OUTCOME",
        away_score="NOT-AN-OUTCOME",
    )
    records.append(extra)
    path, _, _ = build(tmp_path, records)
    audit = json.loads((path.parent / "audit.json").read_text())
    assert audit["outside_requested_seasons"] == {"2024": 1}
    assert "locked-unplayed" not in (path.parent / "labels-2023.csv").read_text()


def test_existing_output_is_never_overwritten(tmp_path):
    path, raw, receipt = build(tmp_path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        preparation().prepare(raw, receipt, path.parent, seasons=[2023])
    assert path.read_bytes() == before


def test_audited_cancellation_omission_is_accounted_without_inventing_schedule(tmp_path):
    records = rows(2022, cancelled=True)
    omitted = records.pop(0)
    raw, receipt = input_files(tmp_path / "input", records, season=2022)
    doc = json.loads(receipt.read_text())
    doc["expected_exceptions"]["2022"]["cancelled"] = [
        {
            "game_id": omitted["game_id"],
            "home_team": omitted["home_team"],
            "away_team": omitted["away_team"],
            "source_row_present": False,
            "reason": "invented audited source omission",
            "audit_ref": "synthetic://cancellation",
        }
    ]
    receipt.write_text(json.dumps(doc))
    path = preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2022])
    audit = json.loads((path.parent / "audit.json").read_text())["seasons"]["2022"]
    assert audit["source_regular_rows"] == 271
    assert audit["regular_scheduled"] == 272
    assert audit["regular_completed"] == 271
    assert audit["omitted_cancelled"] == [omitted["game_id"]]
    assert omitted["game_id"] not in (path.parent / "schedules-2022.csv").read_text()


def test_aliases_neutral_locations_ties_and_dst_are_audited(tmp_path):
    records = rows()
    for row in records:
        for field in ("home_team", "away_team"):
            row[field] = {"LA": "STL", "LAC": "SD", "LV": "OAK"}.get(row[field], row[field])
    records[0].update(location="Neutral", away_score="24")
    path, _, _ = build(tmp_path, records)
    audit = json.loads((path.parent / "audit.json").read_text())["seasons"]["2023"]
    assert audit["neutral"] == [records[0]["game_id"]]
    assert audit["ties"] == [records[0]["game_id"]]
    assert any(
        r["original_home"] == "OAK" and r["home"] == "LV" for r in audit["alias_rows"]
    )  # Original aliases remain individually auditable.
    import csv

    with (path.parent / "schedules-2023.csv").open() as stream:
        prepared = list(csv.DictReader(stream))
    assert prepared[0]["kickoff_ts_utc"] == "2023-09-03T17:00:00.000000Z"
    assert prepared[16 * 10]["kickoff_ts_utc"] == "2023-11-12T18:00:00.000000Z"
    assert not {"OAK", "SD", "STL"} & {r["home_team"] for r in prepared}


def test_pinned_git_blob_and_size_are_verified(tmp_path):
    raw, receipt = input_files(tmp_path / "input")
    doc = json.loads(receipt.read_text())
    doc["source"].update(raw_size=raw.stat().st_size, git_blob_sha1="b" * 40)
    receipt.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="blob"):
        preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2023])
    assert not (tmp_path / "output").exists()


def test_partial_cancelled_score_is_preserved_only_in_raw_audit(tmp_path):
    records = rows(2022, cancelled=True)
    records[0].update(home_score="7", away_score="3")
    path, _, _ = build(tmp_path, records, season=2022, cancelled=True)
    from lab.backtest.score_data import load_manifest

    dataset, _ = load_manifest(path)
    cancelled = next(x for x in dataset.labels if x.game_id == records[0]["game_id"])
    assert cancelled.completed is False and cancelled.home_score is None
    raw_rows = json.loads((path.parent / "source-rows-2022.json").read_text())
    assert raw_rows[0]["home_score"] == "7" and raw_rows[0]["away_score"] == "3"


def test_real_mode_requires_postseason_round_completeness(tmp_path):
    records = rows()
    types = ["WC"] * 6 + ["DIV"] * 4 + ["CON"] * 2 + ["SB"]
    for row, game_type in zip(records[-13:], types, strict=True):
        row["game_type"] = game_type
    records[-1]["game_type"] = "WC"  # Same total, but missing the final round.
    raw, receipt = input_files(tmp_path / "input", records)
    doc = json.loads(receipt.read_text())
    doc["synthetic"] = False
    doc["source"]["audit_ref"] = "https://example.org/invented-audit"
    doc["completeness_rule_ref"] = "https://example.org/invented-count-rules"
    receipt.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="postseason.*round"):
        preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2023])


def test_missing_header_in_empty_csv_is_not_published(tmp_path):
    raw, receipt = input_files(tmp_path / "input")
    content = b"game_id,season\n"
    raw.write_bytes(content)
    doc = json.loads(receipt.read_text())
    doc["source"].update(
        raw_size=len(content),
        raw_sha256=hashlib.sha256(content).hexdigest(),
        git_blob_sha1=hashlib.sha1(
            b"blob " + str(len(content)).encode() + b"\0" + content
        ).hexdigest(),
    )
    receipt.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="headers"):
        preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2023])


def test_symlink_output_parent_is_rejected(tmp_path):
    raw, receipt = input_files(tmp_path / "input")
    destination = tmp_path / "destination"
    destination.mkdir()
    link = tmp_path / "link"
    link.symlink_to(destination, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink|unsafe"):
        preparation().prepare(raw, receipt, link / "output", seasons=[2023])
    assert not (destination / "output").exists()


def test_explicit_warmup_has_31_franchises_before_expansion_and_separate_roles(tmp_path):
    from datetime import date, timedelta

    from nfl_preparation_fixtures import TEAMS

    records = []
    for season in (2001, 2005, 2006):
        teams = [t for t in TEAMS if t != "HOU" or season > 2001]
        template = rows()[0]
        ordinal = 0
        # A cyclic degree-16 graph: each invented team has 16 appearances.
        for i, home in enumerate(teams):
            for offset in range(1, 9):
                away = teams[(i + offset) % len(teams)]
                record = dict(template)
                record.update(
                    game_id=f"warmup-{season}-{ordinal}",
                    season=str(season),
                    gameday=str(date(season, 4, 1) + timedelta(days=ordinal)),
                    week=str(ordinal // 16 + 1),
                    home_team=home,
                    away_team=away,
                )
                records.append(record)
                ordinal += 1
        for j in range(11):
            record = dict(template)
            record.update(
                game_id=f"post-{season}-{j}",
                season=str(season),
                game_type="POST",
                gameday=str(date(season + 1, 1, 1) + timedelta(days=7 * j)),
            )
            records.append(record)
    raw, receipt = input_files(tmp_path / "input", records)
    path = preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2001, 2005, 2006])
    from lab.backtest.score_data import load_manifest

    dataset, manifest = load_manifest(path)
    assert len(dataset.labels) == 793
    assert {(p["season"], p["role"]) for p in manifest["partitions"]} == {
        (2001, "baseline_warmup"),
        (2005, "baseline_warmup"),
        (2006, "development"),
    }
    audit = json.loads((path.parent / "audit.json").read_text())["seasons"]
    assert audit["2001"]["regular_scheduled"] == 248
    assert "HOU" not in audit["2001"]["regular_appearances"]
    assert audit["2005"]["regular_scheduled"] == 256


def test_cross_season_overlaps_fail_before_publishing_compatible_manifest(tmp_path):
    records = rows(2022) + rows(2023)
    records[285]["gameday"] = records[272]["gameday"]
    raw, receipt = input_files(tmp_path / "input", records)
    with pytest.raises(ValueError, match="overlap"):
        preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2022, 2023])
    assert not (tmp_path / "output" / "manifest.json").exists()


def test_truncated_optional_fields_fail_before_publishing_audit(tmp_path):
    raw, receipt = input_files(tmp_path / "input")
    lines = raw.read_text().splitlines()
    lines[1] = lines[1].rsplit(",", 1)[0]  # Omit stadium cell, not any required score field.
    content = ("\n".join(lines) + "\n").encode()
    raw.write_bytes(content)
    doc = json.loads(receipt.read_text())
    doc["source"].update(
        raw_size=len(content),
        raw_sha256=hashlib.sha256(content).hexdigest(),
        git_blob_sha1=hashlib.sha1(
            b"blob " + str(len(content)).encode() + b"\0" + content
        ).hexdigest(),
    )
    receipt.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="CSV.*columns|malformed"):
        preparation().prepare(raw, receipt, tmp_path / "output", seasons=[2023])
    assert not (tmp_path / "output").exists()


def test_saved_receipt_preserves_the_exact_audited_input_bytes(tmp_path):
    path, _, receipt = build(tmp_path)
    manifest = json.loads(path.read_text())
    saved = (path.parent / "receipt.json").read_bytes()
    assert saved == receipt.read_bytes()
    assert hashlib.sha256(saved).hexdigest() == manifest["preparation"]["receipt_sha256"]


def test_zero_week_is_rejected_before_publishing_input(tmp_path):
    records = rows()
    records[0]["week"] = "0"
    with pytest.raises(ValueError, match="positive.*week|week.*positive"):
        build(tmp_path, records)
    assert not (tmp_path / "output").exists()
