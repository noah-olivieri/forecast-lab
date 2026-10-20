"""Slot rule, windows, coverage and MISSED logic for the drivers snapshot bot (spec
2026-10-19-drivers-snapshot-automation-design.md). No network: kickoffs and snapshot dirs are
built in tmp dirs."""

import ast
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lab import drivers_slots as sl

MODULE = Path(sl.__file__)
H, M = timedelta(hours=1), timedelta(minutes=1)
PAST = datetime(2026, 1, 1, tzinfo=UTC)
LIVE = {"t3": PAST, "t48": sl.GO_LIVE_UNSET, "t24": sl.GO_LIVE_UNSET}
ALL_LIVE = {"t3": PAST, "t48": PAST, "t24": PAST}
K = datetime(2026, 10, 25, 17, 0, tzinfo=UTC)  # Sunday 1 PM ET


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def snap(root, created, predicted=(), excluded=(), purpose="main", timing=None, slot=None,
         old_format=False):  # fmt: skip
    """A snapshot dir like jobs/snapshot_drivers.py writes; `excluded` is (game_id, reason)."""
    d = root / created.strftime("%Y-%m-%d") / f"{created:%Y-%m-%dT%H-%M-%S}Z"
    d.mkdir(parents=True)
    meta = {"created_ts": iso(created)}
    if not old_format:
        meta |= {"purpose": purpose, "timing": timing, "slot": slot}
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "predictions.csv").write_text(
        "game_id,p_home\n" + "".join(f"{g},0.5\n" for g in predicted)
    )
    (d / "excluded.csv").write_text(
        "game_id,kickoff_ts,reason\n" + "".join(f"{g},x,{r}\n" for g, r in excluded)
    )
    return d


def records(root):
    recs, warnings = sl.read_snapshots(root)
    assert warnings == []
    return recs


def one_slot(*kickoffs):
    ko = {f"G{i}": k for i, k in enumerate(kickoffs)}
    slots = sl.build_slots(ko)
    assert len(slots) == 1
    return slots[0], ko


# ---- constants and slots ----------------------------------------------------------------------


def test_module_is_stdlib_only():
    top = set()
    for node in ast.walk(ast.parse(MODULE.read_text())):
        if isinstance(node, ast.Import):
            top |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            top.add(node.module.split(".")[0])
    assert top <= set(sys.stdlib_module_names), top


def test_constraint_first_attempt_plus_width_within_count_window():
    assert sl.WINDOWS["t3"][0] + sl.SLOT_WIDTH <= sl.COUNT_WINDOW


def test_windows_and_purposes_are_the_approved_ones():
    assert sl.WINDOWS == {"t48": (48 * H, 45 * H), "t24": (24 * H, 21 * H), "t3": (2 * H, 45 * M)}
    assert sl.PURPOSE == {"t48": "timing", "t24": "timing", "t3": "main"}


def test_build_slots_groups_405_and_425_not_715_and_815():
    ko = {"A": utc(2026, 10, 25, 20, 5), "B": utc(2026, 10, 25, 20, 25),
          "C": utc(2026, 10, 26, 23, 15), "D": utc(2026, 10, 27, 0, 15)}  # fmt: skip
    slots = sl.build_slots(ko)
    assert [(s.id, s.game_ids) for s in slots] == [
        ("2026-10-25T20:05Z", ("A", "B")),
        ("2026-10-26T23:15Z", ("C",)),
        ("2026-10-27T00:15Z", ("D",)),
    ]


def test_slot_width_is_exclusive_at_60_minutes():
    ko = {
        "A": utc(2026, 10, 25, 17, 0),
        "B": utc(2026, 10, 25, 17, 59),
        "C": utc(2026, 10, 25, 18, 0),
    }
    assert [s.game_ids for s in sl.build_slots(ko)] == [("A", "B"), ("C",)]


def test_slots_across_dst_and_london():
    ko = {"LON": utc(2026, 10, 25, 13, 30), "E1": utc(2026, 10, 25, 17), "E2": utc(2026, 10, 25, 17),
          "L1": utc(2026, 10, 25, 20, 5), "L2": utc(2026, 10, 25, 20, 25),
          "SNF": utc(2026, 10, 26, 0, 20),
          "N1": utc(2026, 11, 1, 14, 30), "N2": utc(2026, 11, 1, 18, 0)}  # fmt: skip
    ids = [s.id for s in sl.build_slots(ko)]
    assert ids == ["2026-10-25T13:30Z", "2026-10-25T17:00Z", "2026-10-25T20:05Z",
                   "2026-10-26T00:20Z", "2026-11-01T14:30Z", "2026-11-01T18:00Z"]  # fmt: skip


def test_find_slot_and_load_kickoffs(tmp_path):
    p = tmp_path / "kickoffs.json"
    p.write_text(json.dumps([{"game_id": "G", "away": "A", "home": "H", "kickoff_utc": iso(K)}]))
    ko = sl.load_kickoffs(p)
    assert ko == {"G": K}
    slots = sl.build_slots(ko)
    assert sl.find_slot(slots, "2026-10-25T17:00Z").game_ids == ("G",)
    assert sl.find_slot(slots, "2026-10-25T18:00Z") is None


def test_window_boundaries_per_timing():
    s, _ = one_slot(K)
    assert sl.window(s, "t3") == (K - 2 * H, K - 45 * M)
    assert sl.window(s, "t24") == (K - 24 * H, K - 21 * H)
    assert sl.window(s, "t48") == (K - 48 * H, K - 45 * H)


# ---- reading snapshots and coverage -----------------------------------------------------------


def test_read_snapshots_old_format_and_broken_dirs(tmp_path):
    snap(tmp_path, K - 7 * H, predicted=["G0"], old_format=True)
    broken = tmp_path / "2026-10-25" / "2026-10-25T09-00-00Z"
    broken.mkdir(parents=True)
    (broken / "predictions.csv").write_text("game_id\nG0\n")
    bad_json = snap(tmp_path, K - 6 * H, predicted=["G0"])
    (bad_json / "meta.json").write_text("{not json")
    recs, warnings = sl.read_snapshots(tmp_path)
    assert len(recs) == 1 and recs[0].purpose == "main" and recs[0].timing is None
    assert recs[0].slot is None and recs[0].listed == frozenset({"G0"})
    assert len(warnings) == 2


def test_read_snapshots_missing_root_is_empty(tmp_path):
    assert sl.read_snapshots(tmp_path / "nope") == ([], [])


def test_main_coverage_needs_created_within_3h_and_game_listed(tmp_path):
    a = snap(tmp_path / "a", K - 3 * H, predicted=["G"])
    assert sl.game_covered_main("G", K, records(tmp_path / "a")).path == a
    snap(tmp_path / "b", K - 3 * H - timedelta(seconds=1), predicted=["G"])
    snap(tmp_path / "b", K, predicted=["G"])
    assert sl.game_covered_main("G", K, records(tmp_path / "b")) is None
    snap(tmp_path / "c", K - H, predicted=["G"], purpose="timing", timing="t24")
    assert sl.game_covered_main("G", K, records(tmp_path / "c")) is None
    snap(tmp_path / "d", K - H, excluded=[("G", "no_prediction")])
    assert sl.game_covered_main("G", K, records(tmp_path / "d")) is not None
    snap(tmp_path / "e", K - H, excluded=[("G", "other_slot")])
    assert sl.game_covered_main("G", K, records(tmp_path / "e")) is None


def test_main_coverage_returns_the_earliest_qualifying_record(tmp_path):
    first = snap(tmp_path, K - 2 * H, predicted=["G"])
    snap(tmp_path, K - H, predicted=["G"])
    assert sl.game_covered_main("G", K, records(tmp_path)).path == first


def test_moved_kickoff_uncovers_game(tmp_path):
    snap(tmp_path, K - 2 * H, predicted=["G"])
    recs = records(tmp_path)
    assert sl.game_covered_main("G", K, recs) is not None
    assert sl.game_covered_main("G", K + 2 * H, recs) is None


def test_t3_pair_needs_every_slot_game_covered(tmp_path):
    s, ko = one_slot(K, K + 25 * M)
    snap(tmp_path, K - 2 * H, predicted=["G0"])
    assert not sl.pair_covered(s, "t3", ko, records(tmp_path))
    snap(tmp_path, K - 90 * M, predicted=["G0", "G1"])
    assert sl.pair_covered(s, "t3", ko, records(tmp_path))


def test_timing_pair_covered_only_by_matching_slot_and_timing_label(tmp_path):
    s, ko = one_slot(K)
    snap(tmp_path, K - 23 * H, predicted=["G0"])  # manual snapshot inside the t24 window
    snap(tmp_path, K - 47 * H, predicted=["G0"], purpose="timing", timing="t48", slot=s.id)
    snap(tmp_path, K - 22 * H, predicted=["G0"], purpose="timing", timing="t24", slot="other")
    recs = records(tmp_path)
    assert not sl.pair_covered(s, "t24", ko, recs)
    assert sl.pair_covered(s, "t48", ko, recs)


# ---- needs a run / created_ts / MISSED --------------------------------------------------------


def test_pairs_needing_run_open_uncovered_eligible_only(tmp_path):
    s, ko = one_slot(K)
    slots = [s]
    assert sl.pairs_needing_run(slots, ko, [], K - 2 * H, go_live=LIVE) == [(s, "t3")]
    assert sl.pairs_needing_run(slots, ko, [], K - 45 * M, go_live=LIVE) == []  # closed
    assert sl.pairs_needing_run(slots, ko, [], K - 2 * H - M, go_live=LIVE) == []  # not yet open
    assert sl.pairs_needing_run(slots, ko, [], K - 23 * H, go_live=LIVE) == []  # t24 not live
    assert sl.pairs_needing_run(slots, ko, [], K - 23 * H, go_live=ALL_LIVE) == [(s, "t24")]
    snap(tmp_path, K - 100 * M, predicted=["G0"])
    assert sl.pairs_needing_run(slots, ko, records(tmp_path), K - 90 * M, go_live=LIVE) == []


def test_go_live_applies_to_window_open():
    s, ko = one_slot(K)
    live_after_open = {"t3": K - 2 * H + M, "t48": sl.GO_LIVE_UNSET, "t24": sl.GO_LIVE_UNSET}
    assert sl.pairs_needing_run([s], ko, [], K - H, go_live=live_after_open) == []
    assert not sl.eligible(s, "t3", live_after_open) and sl.eligible(s, "t3", LIVE)


def test_check_created_ts_grace():
    s, _ = one_slot(K)
    close = K - 45 * M
    assert sl.check_created_ts(s, "t3", close + 10 * M) is None
    assert sl.check_created_ts(s, "t3", K - 2 * H) is None
    assert sl.check_created_ts(s, "t3", close + 45 * M) is not None
    assert sl.check_created_ts(s, "t3", K - 2 * H - timedelta(seconds=1)) is not None


def test_missed_t3_after_kickoff_and_commit_time_rule(tmp_path):
    s, ko = one_slot(K)
    d = snap(tmp_path, K - H, predicted=["G0"])
    recs = records(tmp_path)
    late = sl.missed([s], ko, recs, K + H, lambda p: K + M, go_live=LIVE)
    assert len(late) == 1 and "G0" in late[0] and "t3" in late[0]
    assert sl.missed([s], ko, recs, K + H, lambda p: K - M, go_live=LIVE) == []
    assert len(sl.missed([s], ko, recs, K + H, lambda p: None, go_live=LIVE)) == 1
    assert sl.missed([s], ko, [], K + 7 * H, lambda p: None, go_live=LIVE) == []  # lookback
    assert sl.missed([s], ko, [], K - M, lambda p: None, go_live=LIVE) == []  # before kickoff
    assert d.exists()


def test_missed_ignores_slots_before_go_live():
    s, ko = one_slot(K)
    not_live = {"t3": sl.GO_LIVE_UNSET, "t48": sl.GO_LIVE_UNSET, "t24": sl.GO_LIVE_UNSET}
    assert sl.missed([s], ko, [], K + H, lambda p: None, go_live=not_live) == []


def test_missed_timing_after_close_plus_grace(tmp_path):
    s, ko = one_slot(K)
    close = K - 21 * H
    assert sl.missed([s], ko, [], close + 44 * M, lambda p: None, go_live=ALL_LIVE) == []
    out = sl.missed([s], ko, [], close + 45 * M, lambda p: None, go_live=ALL_LIVE)
    assert len(out) == 1 and "t24" in out[0] and s.id in out[0]
    snap(tmp_path, K - 22 * H, predicted=["G0"], purpose="timing", timing="t24", slot=s.id)
    assert sl.missed([s], ko, records(tmp_path), close + 45 * M, lambda p: None,
                     go_live=ALL_LIVE) == []  # fmt: skip


def test_read_snapshots_wrong_shape_meta_is_a_warning_not_a_crash(tmp_path):
    for i, text in enumerate(["[1, 2]", '{"created_ts": null}', '{"created_ts": 5}', "null"]):
        d = snap(tmp_path, K - (i + 1) * H, predicted=["G0"])
        (d / "meta.json").write_text(text)
    snap(tmp_path, K - 9 * H, predicted=["G0"])
    recs, warnings = sl.read_snapshots(tmp_path)
    assert len(recs) == 1 and len(warnings) == 4
