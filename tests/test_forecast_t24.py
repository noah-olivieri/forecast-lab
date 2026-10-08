"""Gate logic of jobs/forecast_t24.py (the pre-registered T-24h rule in RESEARCH_PROTOCOL.md).

No network: kickoffs and forecast files are built in tmp dirs.
"""

import ast
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

JOB = Path(__file__).parent.parent / "jobs" / "forecast_t24.py"
spec = importlib.util.spec_from_file_location("forecast_t24", JOB)
ft = importlib.util.module_from_spec(spec)
sys.modules["forecast_t24"] = ft  # dataclasses with postponed annotations look the module up
spec.loader.exec_module(ft)

K = datetime(2026, 10, 11, 17, 0, tzinfo=UTC)  # a Sunday 1 PM ET kickoff
GO = datetime(2026, 10, 1, tzinfo=UTC)  # stand-in GO_LIVE; first eligible kickoff is GO + 24h
OPEN_AT, CLOSE_AT = K - timedelta(hours=24), K - timedelta(hours=21)


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def kickoffs_file(tmp_path, *games):
    path = tmp_path / "kickoffs.json"
    path.write_text(
        json.dumps(
            [
                {"game_id": gid, "away": "AAA", "home": "HHH", "kickoff_utc": iso(k)}
                for gid, k in games
            ]
        )
    )
    return path


def pick(tmp_path, now, *games, go_live=GO):
    kickoffs = ft.load_kickoffs(kickoffs_file(tmp_path, *games))
    return ft.select(kickoffs, now, tmp_path / "forecasts", go_live=go_live)


def per_game_file(tmp_path, game_id, day="2026-10-11"):
    d = tmp_path / "forecasts" / day
    d.mkdir(parents=True, exist_ok=True)
    (d / f"nfl-t24_{game_id}.csv").write_text("model,game_id\nelo," + game_id + "\n")


def legacy_file(tmp_path, *game_ids):
    d = tmp_path / "forecasts" / "2026-10-08"
    d.mkdir(parents=True, exist_ok=True)
    lines = ["model,game_id"] + [f"elo,{g}" for g in game_ids]
    (d / "nfl_2026-10-08T00-05Z.csv").write_text("\n".join(lines) + "\n")


# ---- window boundaries: [K-24h, K-21h) -------------------------------------------------------


def test_window_is_open_at_exactly_k_minus_24h(tmp_path):
    assert pick(tmp_path, OPEN_AT, ("G1", K)).open_ids == ["G1"]
    assert pick(tmp_path, OPEN_AT - timedelta(seconds=1), ("G1", K)).open_ids == []


def test_window_is_closed_at_exactly_k_minus_21h(tmp_path):
    just_before = pick(tmp_path, CLOSE_AT - timedelta(seconds=1), ("G1", K))
    assert just_before.open_ids == ["G1"] and just_before.missed_ids == []
    at_close = pick(tmp_path, CLOSE_AT, ("G1", K))
    assert at_close.open_ids == [] and at_close.missed_ids == ["G1"]


# ---- eligibility ------------------------------------------------------------------------------


def test_games_before_go_live_plus_24h_are_ignored(tmp_path):
    early = GO + timedelta(hours=24) - timedelta(seconds=1)
    first_ok = GO + timedelta(hours=24)
    now = early - timedelta(hours=22)  # inside early's window
    got = pick(tmp_path, now, ("EARLY", early))
    assert got.open_ids == [] and got.missed_ids == []
    now = first_ok - timedelta(hours=22)
    assert pick(tmp_path, now, ("FIRST", first_ok)).open_ids == ["FIRST"]
    # and an ignored game never shows up as missed once its window has closed
    late = early - timedelta(hours=21) + timedelta(hours=1)
    assert pick(tmp_path, late, ("EARLY", early)).missed_ids == []


def test_unset_go_live_selects_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ft, "GO_LIVE", ft.GO_LIVE_UNSET)
    path = kickoffs_file(tmp_path, ("G1", K))
    code = ft.main(["gate", "--now", iso(K - timedelta(hours=22)), "--kickoffs", str(path),
                    "--forecasts-dir", str(tmp_path / "forecasts")])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0 and "::warning" in out and "GO_LIVE" in out
    assert "G1" not in out.split("game_ids")[-1]


def test_go_live_is_a_module_constant_not_an_input():
    # the dry-run / production value lives in one constant; the CLI has no go-live option
    text = JOB.read_text()
    assert "--go-live" not in text and "--games" not in text


# ---- existing forecasts are skipped ------------------------------------------------------------


def test_existing_per_game_forecast_is_skipped(tmp_path):
    per_game_file(tmp_path, "G1")
    got = pick(tmp_path, OPEN_AT + timedelta(hours=1), ("G1", K), ("G2", K))
    assert got.open_ids == ["G2"]


def test_game_logged_only_in_a_legacy_batch_csv_is_skipped(tmp_path):
    legacy_file(tmp_path, "G1")
    got = pick(tmp_path, OPEN_AT + timedelta(hours=1), ("G1", K), ("G2", K))
    assert got.open_ids == ["G2"]


def test_game_with_forecast_is_not_reported_missed(tmp_path):
    per_game_file(tmp_path, "G1")
    legacy_file(tmp_path, "G2")
    got = pick(tmp_path, CLOSE_AT + timedelta(minutes=30), ("G1", K), ("G2", K), ("G3", K))
    assert got.missed_ids == ["G3"]


def test_forecast_game_ids_reads_names_and_rows(tmp_path):
    per_game_file(tmp_path, "FROM_NAME")
    legacy_file(tmp_path, "ROW_A", "ROW_B")
    assert ft.forecast_game_ids(tmp_path / "forecasts") == {"FROM_NAME", "ROW_A", "ROW_B"}
    assert ft.forecast_game_ids(tmp_path / "nowhere") == set()


# ---- missed games --------------------------------------------------------------------------------


def test_missed_only_reported_inside_the_lookback(tmp_path):
    inside = CLOSE_AT + ft.MISSED_LOOKBACK - timedelta(seconds=1)
    assert pick(tmp_path, inside, ("G1", K)).missed_ids == ["G1"]
    assert pick(tmp_path, CLOSE_AT + ft.MISSED_LOOKBACK, ("G1", K)).missed_ids == []
    assert ft.MISSED_LOOKBACK == timedelta(hours=6)


def test_gate_fails_on_a_missed_game_but_still_lists_open_games(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ft, "GO_LIVE", GO)
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    now = CLOSE_AT + timedelta(hours=1)  # MISSED_G's window closed an hour ago
    open_kick = now + timedelta(hours=23)  # OPEN_G is 23h from kickoff: window open
    path = kickoffs_file(tmp_path, ("MISSED_G", K), ("OPEN_G", open_kick))
    code = ft.main(["gate", "--now", iso(now), "--kickoffs", str(path),
                    "--forecasts-dir", str(tmp_path / "forecasts")])  # fmt: skip
    printed = capsys.readouterr().out
    assert code == 1
    assert "::error" in printed and "MISSED_G" in printed
    lines = out.read_text().splitlines()
    assert "game_ids=OPEN_G" in lines and "missed=true" in lines


def test_gate_with_nothing_to_do_exits_zero_and_writes_empty_outputs(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(ft, "GO_LIVE", GO)
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    path = kickoffs_file(tmp_path, ("G1", K))
    code = ft.main(["gate", "--now", iso(K - timedelta(days=3)), "--kickoffs", str(path),
                    "--forecasts-dir", str(tmp_path / "forecasts")])  # fmt: skip
    assert code == 0
    assert out.read_text().splitlines() == ["game_ids=", "missed=false"]
    assert "::error" not in capsys.readouterr().out


def test_gate_lists_every_open_game_comma_separated_in_kickoff_order(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "GO_LIVE", GO)
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    path = kickoffs_file(tmp_path, ("B", K), ("A", K), ("C", K + timedelta(hours=1)))
    code = ft.main(["gate", "--now", iso(OPEN_AT + timedelta(hours=1)), "--kickoffs", str(path),
                    "--forecasts-dir", str(tmp_path / "forecasts")])  # fmt: skip
    assert code == 0 and "game_ids=A,B,C" in out.read_text().splitlines()


def test_gate_crash_exits_2_not_1(tmp_path):
    bad = tmp_path / "kickoffs.json"
    bad.write_text("not json")
    code = ft.main(["gate", "--now", iso(K), "--kickoffs", str(bad),
                    "--forecasts-dir", str(tmp_path / "forecasts")])  # fmt: skip
    assert code == 2  # exit 1 is reserved for "a game was missed"


def test_naive_now_is_rejected(tmp_path):
    path = kickoffs_file(tmp_path, ("G1", K))
    code = ft.main(["gate", "--now", "2026-10-10T13:35:00", "--kickoffs", str(path),
                    "--forecasts-dir", str(tmp_path / "forecasts")])  # fmt: skip
    assert code == 2


# ---- the gate must run before `uv sync` ----------------------------------------------------------


def test_module_level_imports_are_stdlib_only():
    tree = ast.parse(JOB.read_text())
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            top.add((node.module or "").split(".")[0])
    assert top <= set(sys.stdlib_module_names), top
