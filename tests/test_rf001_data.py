import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from rf001_fixtures import label, module, schedule


def data():
    return module("lab.backtest.score_data")


def test_finish_boundary_and_latest_admissible_revision():
    kick = datetime(2011, 9, 1, 17, tzinfo=UTC)
    old = label(published_ts=(kick + timedelta(hours=6)).isoformat())
    correction = label(
        revision_id="l2",
        home_score=3,
        published_ts=(kick + timedelta(days=2)).isoformat(),
        fetched_ts=(kick + timedelta(days=2, hours=1)).isoformat(),
    )
    ds = data().Dataset.from_rows([schedule()], [old, correction], "strict_pit")
    assert ds.eligible(kick + timedelta(hours=4)) == []
    assert ds.eligible(kick + timedelta(hours=6)) == []
    before = ds.eligible(kick + timedelta(days=1))
    assert len(before) == 1 and before[0].label.home_score == 24
    assert ds.eligible(kick + timedelta(days=3))[0].label.revision_id == "l2"


def test_reconstructed_is_not_badged_as_historical_publication():
    row = label(
        published_ts=None,
        fetched_ts="2026-10-01T00:00:00Z",
        availability_evidence="retrospective_fetch",
    )
    strict = data().Dataset.from_rows([schedule()], [row], "strict_pit")
    reconstructed = data().Dataset.from_rows([schedule()], [row], "reconstructed_scores")
    cutoff = datetime(2011, 9, 2, tzinfo=UTC)
    assert strict.eligible(cutoff) == []
    assert len(reconstructed.eligible(cutoff)) == 1


def test_missing_kickoff_excluded_duplicates_and_alias_collisions_rejected():
    ds = data().Dataset.from_rows(
        [schedule(kickoff_ts_utc=None)], [label()], "reconstructed_scores"
    )
    assert ds.targets() == []
    assert ds.exclusions[0]["reason"] == "missing_kickoff"
    with pytest.raises(ValueError, match="duplicate"):
        data().Dataset.from_rows([schedule(), schedule()], [], "reconstructed_scores")
    with pytest.raises(ValueError, match="same team"):
        data().Dataset.from_rows(
            [schedule(home_team="OAK", away_team="LV")], [], "reconstructed_scores"
        )
    with pytest.raises(ValueError, match="timezone"):
        data().Dataset.from_rows(
            [schedule(kickoff_ts_utc="2011-09-01T17:00:00")], [], "reconstructed_scores"
        )


def test_score_bearing_schedule_rejected_and_future_labels_cannot_enter_history():
    with pytest.raises(ValueError, match="score-bearing"):
        data().Dataset.from_rows([schedule(home_score=99)], [], "reconstructed_scores")
    later = datetime(2011, 9, 8, 17, tzinfo=UTC)
    a = data().Dataset.from_rows(
        [schedule(), schedule("g2", later)],
        [label(), label("g2", later, home_score=999)],
        "reconstructed_scores",
    )
    assert [x.game.game_id for x in a.eligible(later - timedelta(days=1))] == ["g1"]


def test_holdout_or_mixed_manifest_rejected_before_any_artifact_access(tmp_path):
    manifest = {
        "schema_version": 1,
        "cohort": "reconstructed_scores",
        "synthetic": True,
        "partitions": [
            {
                "path": "never-open.csv",
                "season": 2024,
                "role": "development",
                "kind": "schedules",
                "sha256": "a" * 64,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="holdout|season"):
        data().load_manifest(path)
    manifest["partitions"][0].update(season=2023, seasons=[2023, 2024])
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="mixed"):
        data().load_manifest(path)


def test_pinned_local_csv_loaded_and_bad_hash_fails(tmp_path):
    row = schedule()
    path = tmp_path / "schedule.csv"
    with path.open("w") as f:
        writer = csv.DictWriter(f, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    manifest = {
        "schema_version": 1,
        "cohort": "reconstructed_scores",
        "synthetic": True,
        "partitions": [
            {
                "path": path.name,
                "season": 2011,
                "role": "development",
                "kind": "schedules",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        ],
    }
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest))
    ds, provenance = data().load_manifest(mp)
    assert ds.targets()[0].game_id == "g1"
    assert provenance["synthetic"] is True
    path.write_text("different content")
    with pytest.raises(ValueError, match="hash"):
        data().load_manifest(mp)


def test_unfinished_scores_are_not_training_labels():
    cutoff = datetime(2011, 9, 2, tzinfo=UTC)
    incomplete = data().Dataset.from_rows(
        [schedule()], [label(completed=False)], "reconstructed_scores"
    )
    assert incomplete.eligible(cutoff) == []


def test_unreferenced_availability_cannot_establish_strict_eligibility():
    cutoff = datetime(2011, 9, 2, tzinfo=UTC)
    bare = data().Dataset.from_rows([schedule()], [label(evidence_ref="")], "strict_pit")
    assert bare.eligible(cutoff) == []


def test_schedule_revisions_do_not_double_count_missing_versions():
    rows = [schedule(kickoff_ts_utc=None), schedule(revision_id="s2",
                                                 fetched_ts="2011-08-27T00:00:00Z")]
    ds = data().Dataset.from_rows(rows, [label()], "reconstructed_scores")
    assert len(ds.targets()) == 1 and ds.exclusions == []


def test_game_identity_cannot_change_between_schedule_revisions():
    with pytest.raises(ValueError, match="identity"):
        data().Dataset.from_rows(
            [schedule(), schedule(revision_id="s2", home_team="CCC")],
            [label()],
            "reconstructed_scores",
        )


def test_same_time_conflicting_label_revisions_are_ambiguous():
    with pytest.raises(ValueError, match="ambiguous"):
        data().Dataset.from_rows(
            [schedule()], [label(), label(revision_id="l2", home_score=3)], "strict_pit"
        )


def test_symlinked_manifest_or_partition_is_rejected_without_reading_target(tmp_path):
    target = tmp_path / "private.txt"
    target.write_text("not game data")
    linked_manifest = tmp_path / "linked.json"
    linked_manifest.symlink_to(target)
    with pytest.raises(ValueError, match="unsafe"):
        data().load_manifest(linked_manifest)
    artifact = tmp_path / "linked.csv"
    artifact.symlink_to(target)
    mp = tmp_path / "manifest.json"
    mp.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "synthetic": True,
                "cohort": "reconstructed_scores",
                "partitions": [
                    {
                        "path": "linked.csv",
                        "season": 2011,
                        "kind": "schedules",
                        "role": "development",
                        "sha256": "a" * 64,
                    }
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="unsafe"):
        data().load_manifest(mp)


def test_latest_available_withdrawn_score_does_not_fall_back_to_old_completed_score():
    kick = datetime(2011, 9, 1, 17, tzinfo=UTC)
    withdrawal = label(
        revision_id="withdrawn",
        completed=False,
        home_score=None,
        away_score=None,
        published_ts="2011-09-03T00:00:00Z",
        fetched_ts="2011-09-03T01:00:00Z",
    )
    ds = data().Dataset.from_rows([schedule()], [label(), withdrawal], "strict_pit")
    assert len(ds.eligible(kick + timedelta(days=1))) == 1
    assert ds.eligible(kick + timedelta(days=3)) == []
    assert ds.evaluation_label("g1") is None


def test_latest_reconstructed_schedule_missing_time_is_not_imputed_from_old_version():
    newest = schedule(
        revision_id="s2",
        kickoff_ts_utc=None,
        published_ts="2011-08-28T00:00:00Z",
        fetched_ts="2011-08-28T01:00:00Z",
    )
    ds = data().Dataset.from_rows([schedule(), newest], [label()], "reconstructed_scores")
    assert ds.targets() == []
    assert len(ds.exclusions) == 1
    assert ds.exclusions[0]["reason"] == "missing_kickoff"
