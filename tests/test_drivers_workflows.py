"""Workflow files and shell scripts around the automated NFL Drivers snapshots (spec
2026-10-19-drivers-snapshot-automation-design.md). No network: git runs against local bare repos
in tmp dirs."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_forecast_workflows import clone, commit_file, git, make_remote

REPO = Path(__file__).parent.parent
PUSH = REPO / ".github" / "scripts" / "push_drivers.sh"
SNAP = "drivers_snapshots/2026-10-25/2026-10-25T15-10-00Z"
FILES = ("meta.json", "predictions.csv", "inputs/upcoming.csv")


def push(repo, tmp_path, *args):
    summary = tmp_path / "summary.md"
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_SERVER_URL": "https://gh",
           "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "123"}  # fmt: skip
    r = subprocess.run(
        ["bash", str(PUSH), *args], cwd=repo, env=env, capture_output=True, text=True, check=False
    )
    return r, summary


def write_snapshot(repo, snap=SNAP, tag="bot"):
    for name in FILES:
        p = repo / snap / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{tag} {name}\n")


# ---- push_drivers.sh ---------------------------------------------------------------------------


def test_push_drivers_pushes_only_the_snapshot_dir_and_summarises(tmp_path):
    bare = make_remote(tmp_path)
    repo = clone(tmp_path, bare, "w")
    write_snapshot(repo)
    (repo / "notes.txt").write_text("untracked, must not be committed\n")
    (repo / "README.md").write_text("modified, must not be committed\n")
    r, summary = push(repo, tmp_path, SNAP, "t3 slot 2026-10-25T17:00Z")
    assert r.returncode == 0, r.stderr
    head = git(repo, "rev-parse", "HEAD")
    assert git(bare, "rev-parse", "main") == head
    assert sorted(git(repo, "show", "--name-only", "--format=", "HEAD").splitlines()) == sorted(
        f"{SNAP}/{n}" for n in FILES
    )
    msg = git(repo, "log", "-1", "--format=%B")
    assert msg.startswith("snapshot: drivers 2026-10-25T15-10-00Z t3 slot 2026-10-25T17:00Z")
    assert "https://gh/o/r/actions/runs/123" in msg
    assert git(repo, "log", "-1", "--format=%an") == "github-actions[bot]"
    text = summary.read_text()
    assert head in text
    assert hashlib.sha256((repo / SNAP / "meta.json").read_bytes()).hexdigest() in text


def test_push_drivers_retries_after_a_rejected_push(tmp_path):
    bare = make_remote(tmp_path)
    repo, other = clone(tmp_path, bare, "w"), clone(tmp_path, bare, "o")
    commit_file(other, "forecasts/2026-10-24/nfl-t24_X.csv", "model,game_id\nelo,X\n")
    git(other, "push", "-q", "origin", "main")  # the forecast bot pushed meanwhile
    write_snapshot(repo)
    r, _ = push(repo, tmp_path, SNAP, "t3")
    assert r.returncode == 0, r.stderr
    assert git(bare, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
    assert git(bare, "show", "main:forecasts/2026-10-24/nfl-t24_X.csv").startswith("model")
    assert git(bare, "show", f"main:{SNAP}/meta.json") == "bot meta.json"


def test_push_drivers_aborts_if_the_dir_was_already_added(tmp_path):
    bare = make_remote(tmp_path)
    repo, other = clone(tmp_path, bare, "w"), clone(tmp_path, bare, "o")
    write_snapshot(other, tag="other")
    git(other, "add", "drivers_snapshots")
    git(other, "commit", "-q", "-m", "other run")
    git(other, "push", "-q", "origin", "main")
    write_snapshot(repo)
    r, _ = push(repo, tmp_path, SNAP, "t3")
    assert r.returncode == 1
    assert git(bare, "show", f"main:{SNAP}/meta.json") == "other meta.json"  # untouched
    assert not (repo / ".git" / "rebase-merge").exists()
    assert not (repo / ".git" / "rebase-apply").exists()


def test_push_drivers_refuses_outside_prefix_existing_files_and_empty_dir(tmp_path):
    bare = make_remote(tmp_path)
    repo = clone(tmp_path, bare, "w")
    (repo / "forecasts" / "x").mkdir(parents=True)
    (repo / "forecasts" / "x" / "a.csv").write_text("a\n")
    assert push(repo, tmp_path, "forecasts/x", "t3")[0].returncode == 1  # wrong prefix
    assert push(repo, tmp_path, "drivers_snapshots/../forecasts/x", "t3")[0].returncode == 1
    empty = repo / "drivers_snapshots" / "2026-10-25" / "2026-10-25T16-00-00Z"
    empty.mkdir(parents=True)
    assert push(repo, tmp_path, str(empty.relative_to(repo)), "t3")[0].returncode == 1
    write_snapshot(repo)
    git(repo, "add", "drivers_snapshots")
    git(repo, "commit", "-q", "-m", "manual")
    (repo / SNAP / "meta.json").write_text("CHANGED\n")
    assert push(repo, tmp_path, SNAP, "t3")[0].returncode == 1  # already tracked: no edits
    assert git(bare, "log", "--format=%s", "main").splitlines() == ["c"]  # nothing was pushed
    assert push(repo, tmp_path, SNAP)[0].returncode == 1  # label is required
