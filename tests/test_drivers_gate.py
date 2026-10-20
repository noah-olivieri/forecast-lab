"""jobs/drivers_gate.py: the cheap pre-install gate and per-pair check. No network: kickoffs and
snapshot dirs are built in tmp dirs."""

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab import drivers_slots as sl

REPO = Path(__file__).parent.parent
JOB = REPO / "jobs" / "drivers_gate.py"
spec = importlib.util.spec_from_file_location("drivers_gate", JOB)
dg = importlib.util.module_from_spec(spec)
sys.modules["drivers_gate"] = dg
spec.loader.exec_module(dg)

sys.path.insert(0, str(Path(__file__).parent))
from test_drivers_slots import iso, snap
from test_drivers_snapshot import git, make_repo

H, M = timedelta(hours=1), timedelta(minutes=1)
K = datetime(2026, 10, 25, 17, 0, tzinfo=UTC)
SLOT = "2026-10-25T17:00Z"
PAST = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(
        sl, "GO_LIVE", {"t3": PAST, "t48": sl.GO_LIVE_UNSET, "t24": sl.GO_LIVE_UNSET}
    )


@pytest.fixture
def out(tmp_path, monkeypatch):
    path = tmp_path / "gh_output"
    path.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))

    def read():
        return dict(line.split("=", 1) for line in path.read_text().splitlines())

    return read


def kickoffs(tmp_path, **games):
    p = tmp_path / "kickoffs.json"
    p.write_text(json.dumps([
        {"game_id": g, "away": "A", "home": "H", "kickoff_utc": iso(k)} for g, k in games.items()
    ]))  # fmt: skip
    return p


def run(tmp_path, *args):
    return dg.main([*args, "--kickoffs", str(kickoffs(tmp_path, G=K)),
                    "--snapshots", str(tmp_path / "snaps")])  # fmt: skip


def test_drivers_cron_constant_avoids_existing_minutes():
    minutes = {int(m) for m in dg.DRIVERS_CRON.split()[0].split(",")}
    assert minutes == {4, 19, 34, 49}
    assert not minutes & {7, 22, 37, 52, 11, 26, 41, 56, 23, 17}


def test_gate_outputs_open_t3_pair_as_json(tmp_path, out, live):
    assert run(tmp_path, "gate", "--now", iso(K - 90 * M)) == 0
    o = out()
    assert json.loads(o["pairs"]) == [{"slot": SLOT, "timing": "t3"}]
    assert o["missed"] == "false"


def test_gate_outside_windows_outputs_empty_list(tmp_path, out, live):
    assert run(tmp_path, "gate", "--now", iso(K - 5 * H)) == 0
    assert out() == {"pairs": "[]", "missed": "false"}


def test_gate_reports_missed_and_exits_1(tmp_path, out, live, monkeypatch, capsys):
    monkeypatch.setattr(dg, "git_commit_time", lambda path: None)
    assert run(tmp_path, "gate", "--now", iso(K + H)) == 1
    assert out()["missed"] == "true"
    assert "::error title=Drivers snapshot MISSED::t3 G" in capsys.readouterr().out


def test_gate_with_unset_go_live_finds_nothing_and_warns(tmp_path, out, capsys, monkeypatch):
    monkeypatch.setattr(sl, "GO_LIVE", dict.fromkeys(sl.TIMINGS, sl.GO_LIVE_UNSET))
    assert run(tmp_path, "gate", "--now", iso(K - 90 * M)) == 0
    assert out()["pairs"] == "[]"
    assert "::warning title=GO_LIVE unset" in capsys.readouterr().out


def test_gate_warns_about_unreadable_snapshots(tmp_path, out, live, capsys):
    (tmp_path / "snaps" / "2026-10-25" / "2026-10-25T09-00-00Z").mkdir(parents=True)
    assert run(tmp_path, "gate", "--now", iso(K - 90 * M)) == 0
    assert "::warning title=Unreadable snapshot" in capsys.readouterr().out
    assert json.loads(out()["pairs"]) == [{"slot": SLOT, "timing": "t3"}]


def test_gate_crash_exits_2(tmp_path, out):
    assert dg.main(["gate", "--kickoffs", str(tmp_path / "missing.json")]) == 2


def test_check_open_and_uncovered_says_run(tmp_path, out, live):
    assert run(tmp_path, "check", "--slot", SLOT, "--timing", "t3", "--now", iso(K - H)) == 0
    assert out() == {"run": "true"}


def test_check_after_push_says_no_run(tmp_path, out, live):
    snap(tmp_path / "snaps", K - 100 * M, predicted=["G"])
    assert run(tmp_path, "check", "--slot", SLOT, "--timing", "t3", "--now", iso(K - H)) == 0
    assert out() == {"run": "false"}


def test_check_closed_window_says_no_run(tmp_path, out, live):
    assert run(tmp_path, "check", "--slot", SLOT, "--timing", "t3", "--now", iso(K - 30 * M)) == 0
    assert out() == {"run": "false"}


def test_check_unknown_slot_says_no_run(tmp_path, out, live, capsys):
    assert run(tmp_path, "check", "--slot", "2026-10-25T18:00Z", "--timing", "t3",
               "--now", iso(K - H)) == 0  # fmt: skip
    assert out() == {"run": "false"}
    assert "::warning" in capsys.readouterr().out


def test_git_commit_time_none_for_untracked_and_set_for_committed(tmp_path):
    repo = make_repo(tmp_path, "lab")
    d = repo / "drivers_snapshots" / "2026-10-25" / "2026-10-25T15-00-00Z"
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{}")
    assert dg.git_commit_time(d, repo) is None
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "snap")
    ts = dg.git_commit_time(d, repo)
    assert ts == datetime(2026, 10, 1, tzinfo=UTC)  # GIT_COMMITTER_DATE of the test helper


def test_gate_runs_with_plain_python_without_site_packages(tmp_path):
    gh = tmp_path / "gh_output"
    r = subprocess.run(
        [sys.executable, "-I", "-S", str(JOB), "gate", "--now", iso(K - 90 * M),
         "--kickoffs", str(kickoffs(tmp_path, G=K)), "--snapshots", str(tmp_path / "snaps")],
        env={"GITHUB_OUTPUT": str(gh), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
        check=False,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert "pairs=" in gh.read_text()
