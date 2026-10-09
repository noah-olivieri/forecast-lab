import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rf001_fixtures import label, module, schedule
from test_rf001_runner import manifest


@pytest.mark.parametrize(
    "kind,key",
    [
        ("schedule", "kickoff_ts_utc"),
        ("label", "completed"),
        ("label", "home_score"),
        ("schedule", "location"),
    ],
)
def test_missing_required_fields_fail_instead_of_becoming_exclusions(kind, key):
    s, l = schedule(), label()
    del (s if kind == "schedule" else l)[key]
    with pytest.raises(ValueError, match="required.*(field|header)"):
        module("lab.backtest.score_data").Dataset.from_rows([s], [l], "reconstructed_scores")


@pytest.mark.parametrize("value", ["TRUE", "yes", "1.0", "", None, 1.0, 2, "no"])
def test_invalid_completed_values_raise_instead_of_becoming_unlabelled(value):
    with pytest.raises(ValueError, match="completed"):
        module("lab.backtest.score_data").Dataset.from_rows(
            [schedule()], [label(completed=value)], "reconstructed_scores"
        )


@pytest.mark.parametrize("cohort", ["strict_pit", "reconstructed_scores"])
def test_equal_time_schedule_revisions_cannot_use_text_id_order(cohort):
    rows = [
        schedule(revision_id="r9"),
        schedule(revision_id="r10", kickoff_ts_utc="2011-09-02T00:20:00Z"),
    ]
    with pytest.raises(ValueError, match="ambiguous.*schedule"):
        module("lab.backtest.score_data").Dataset.from_rows(rows, [label()], cohort)


def test_multiple_revisions_require_one_explicit_order_clock():
    first = schedule(published_ts=None, first_seen_ts=None, fetched_ts=None)
    second = schedule(
        revision_id="r2", published_ts=None, first_seen_ts=None, fetched_ts="2011-08-26T00:00:00Z"
    )
    with pytest.raises(ValueError, match="revision.*clock"):
        module("lab.backtest.score_data").Dataset.from_rows(
            [first, second], [label()], "reconstructed_scores"
        )


def test_duplicate_physical_game_ids_rejected_but_a_reschedule_is_valid():
    data = module("lab.backtest.score_data")
    with pytest.raises(ValueError, match="physical"):
        data.Dataset.from_rows([schedule("id-one"), schedule("id-two")], [], "reconstructed_scores")
    revised = schedule(
        revision_id="r2",
        kickoff_ts_utc="2011-09-02T00:20:00Z",
        published_ts="2011-08-27T00:00:00Z",
        fetched_ts="2011-08-27T01:00:00Z",
    )
    ds = data.Dataset.from_rows([schedule(), revised], [label()], "reconstructed_scores")
    assert len(ds.targets()) == 1
    assert ds.targets()[0].kickoff == datetime(2011, 9, 2, 0, 20, tzinfo=UTC)


def test_overlapping_team_games_are_rejected():
    with pytest.raises(ValueError, match="overlapping"):
        module("lab.backtest.score_data").Dataset.from_rows(
            [
                schedule(),
                schedule("different", away_team="CCC", kickoff_ts_utc="2011-09-01T18:00:00Z"),
            ],
            [],
            "reconstructed_scores",
        )


def test_empty_file_still_requires_correct_headers(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("game_id,season,kickoff_ts\n")
    mp = tmp_path / "manifest.json"
    mp.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "synthetic": True,
                "cohort": "reconstructed_scores",
                "partitions": [
                    {
                        "path": "empty.csv",
                        "kind": "schedules",
                        "season": 2011,
                        "role": "development",
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="required.*header"):
        module("lab.backtest.score_data").load_manifest(mp)


def test_parser_uses_the_exact_hashed_bytes_even_when_path_changes(tmp_path, monkeypatch):
    mp = manifest(tmp_path, [schedule()], [label()])
    target = tmp_path / "schedules-2011.csv"
    original = Path.read_bytes

    def swapped(self):
        raw = original(self)
        if self == target:
            rows = [schedule(kickoff_ts_utc="2011-09-02T00:20:00Z")]
            with self.open("w") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0])
                writer.writeheader()
                writer.writerows(rows)
        return raw

    monkeypatch.setattr(Path, "read_bytes", swapped)
    ds, _ = module("lab.backtest.score_data").load_manifest(mp)
    assert ds.targets()[0].kickoff == datetime(2011, 9, 1, 17, tzinfo=UTC)


def test_synthetic_flag_requires_invented_evidence_markers(tmp_path):
    mp = manifest(
        tmp_path, [schedule(evidence_ref="https://real-source.invalid/archive")], [label()]
    )
    with pytest.raises(ValueError, match="synthetic.*marker"):
        module("lab.backtest.score_data").load_manifest(mp)


def test_strict_flex_revision_uses_only_the_declared_publication_clock():
    data = module("lab.backtest.score_data")
    later = schedule(
        revision_id="flex",
        kickoff_ts_utc="2011-09-02T00:20:00Z",
        published_ts="2011-08-27T00:00:00Z",
        fetched_ts="2011-08-27T01:00:00Z",
    )
    ds = data.Dataset.from_rows([schedule(), later], [label()], "strict_pit")
    assert ds.schedules_at(datetime(2011, 8, 26, 18, tzinfo=UTC))["g1"].vintage.revision_id == "s1"
    assert ds.schedules_at(datetime(2011, 8, 28, tzinfo=UTC))["g1"].vintage.revision_id == "flex"
    assert ds.targets()[0].as_of == datetime(2011, 9, 1, 0, 20, tzinfo=UTC)
