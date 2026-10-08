"""Workflow files and shell scripts around the automated T-24h forecast. No network: git runs
against local bare repos in tmp dirs."""

import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
PUSH = REPO / ".github" / "scripts" / "push_forecasts.sh"
GUARD = REPO / ".github" / "scripts" / "check_forecasts_append_only.sh"

spec = importlib.util.spec_from_file_location("forecast_t24", REPO / "jobs" / "forecast_t24.py")
ft = importlib.util.module_from_spec(spec)
sys.modules["forecast_t24"] = ft
spec.loader.exec_module(ft)


def workflow(name):
    doc = yaml.safe_load((WORKFLOWS / name).read_text())
    doc["on"] = doc.pop(True, doc.get("on"))  # YAML 1.1 reads a bare `on:` key as True
    return doc


def uses(name):
    return set(re.findall(r"uses:\s*(\S+)", (WORKFLOWS / name).read_text()))


# ---- forecast.yml ------------------------------------------------------------------------------


def test_forecast_cron_equals_the_constant():
    crons = [s["cron"] for s in workflow("forecast.yml")["on"]["schedule"]]
    assert crons == [ft.FORECAST_CRON]


def test_manual_run_has_no_inputs_so_nobody_can_pick_games():
    trigger = workflow("forecast.yml")["on"]["workflow_dispatch"]
    assert not (trigger or {}).get("inputs")
    text = (WORKFLOWS / "forecast.yml").read_text()
    assert "github.event.inputs" not in text and "inputs." not in text


def test_forecast_runs_are_serialised_without_cancelling():
    wf = workflow("forecast.yml")
    assert wf["concurrency"] == {"group": "forecast", "cancel-in-progress": False}
    for job in wf["jobs"].values():  # the data-branch group would cancel pending collect runs
        assert "data-branch" not in str(job.get("concurrency", ""))


def test_forecast_job_runs_only_if_the_gate_found_games():
    wf = workflow("forecast.yml")
    assert wf["jobs"]["forecast"]["needs"] == "gate"
    assert "game_ids" in wf["jobs"]["forecast"]["if"]
    assert "missed" in wf["jobs"]["alert"]["if"]  # a miss fails the run so GitHub emails


def test_forecast_workflow_uses_only_action_versions_from_collect_yml():
    allowed = uses("collect.yml")
    assert uses("forecast.yml") <= allowed and uses("ci.yml") <= allowed


def test_kickoffs_refresh_is_daily():
    assert [s["cron"] for s in workflow("kickoffs.yml")["on"]["schedule"]] == ["17 10 * * *"]


def test_ci_runs_tests_lint_and_the_forecast_guard_on_push_and_pr():
    wf = workflow("ci.yml")
    assert {"push", "pull_request"} <= set(wf["on"])
    text = (WORKFLOWS / "ci.yml").read_text()
    assert "uv run pytest -q" in text and "uv run ruff check ." in text
    assert "check_forecasts_append_only.sh" in text


# ---- helpers for the git-based script tests ------------------------------------------------------


def git(cwd, *args, check=True):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}  # fmt: skip
    r = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    if check and r.returncode:
        raise AssertionError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def commit_file(repo, rel, text, msg="c"):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", msg)


def make_remote(tmp_path):
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    git(seed, "checkout", "-q", "-b", "main")
    commit_file(seed, "README.md", "x\n")
    git(seed, "push", "-q", "origin", "main")
    return bare


def clone(tmp_path, bare, name):
    path = tmp_path / name
    git(tmp_path, "clone", "-q", str(bare), str(path))
    return path


def push_script(repo, tmp_path, *paths):
    summary = tmp_path / "summary.md"
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_SERVER_URL": "https://gh",
           "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "123"}  # fmt: skip
    r = subprocess.run(
        ["bash", str(PUSH), *paths], cwd=repo, env=env, capture_output=True, text=True, check=False
    )
    return r, summary


NEW = "forecasts/2026-10-11/nfl-t24_G1.csv"


# ---- push_forecasts.sh -------------------------------------------------------------------------


def test_push_script_pushes_only_the_named_new_file_and_summarises(tmp_path):
    bare = make_remote(tmp_path)
    repo = clone(tmp_path, bare, "w")
    (repo / NEW).parent.mkdir(parents=True)
    (repo / NEW).write_text("model,game_id\nelo,G1\n")
    (repo / "notes.txt").write_text("untracked, must not be committed\n")
    (repo / "README.md").write_text("modified, must not be committed\n")
    r, summary = push_script(repo, tmp_path, NEW)
    assert r.returncode == 0, r.stderr
    head = git(repo, "rev-parse", "HEAD")
    assert git(bare, "rev-parse", "main") == head
    assert git(repo, "show", "--name-only", "--format=", "HEAD").splitlines() == [NEW]
    assert "https://gh/o/r/actions/runs/123" in git(repo, "log", "-1", "--format=%B")
    assert git(repo, "log", "-1", "--format=%an") == "github-actions[bot]"
    text = summary.read_text()
    assert hashlib.sha256((repo / NEW).read_bytes()).hexdigest() in text and head in text


def test_push_script_retries_after_a_rejected_push(tmp_path):
    bare = make_remote(tmp_path)
    repo, other = clone(tmp_path, bare, "w"), clone(tmp_path, bare, "o")
    commit_file(other, "site/x.txt", "other work\n")
    git(other, "push", "-q", "origin", "main")  # origin moves while we hold a stale checkout
    (repo / NEW).parent.mkdir(parents=True)
    (repo / NEW).write_text("model,game_id\nelo,G1\n")
    r, _ = push_script(repo, tmp_path, NEW)
    assert r.returncode == 0, r.stderr
    assert git(bare, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
    assert git(bare, "show", "main:site/x.txt") == "other work"
    assert git(bare, "show", f"main:{NEW}").startswith("model,game_id")


def test_push_script_aborts_if_another_run_already_added_the_file(tmp_path):
    bare = make_remote(tmp_path)
    repo, other = clone(tmp_path, bare, "w"), clone(tmp_path, bare, "o")
    commit_file(other, NEW, "model,game_id\nOTHER_RUN,G1\n")
    git(other, "push", "-q", "origin", "main")
    (repo / NEW).parent.mkdir(parents=True)
    (repo / NEW).write_text("model,game_id\nelo,G1\n")
    r, _ = push_script(repo, tmp_path, NEW)
    assert r.returncode == 1
    assert git(bare, "show", f"main:{NEW}") == "model,game_id\nOTHER_RUN,G1"  # untouched
    assert not (repo / ".git" / "rebase-merge").exists()
    assert not (repo / ".git" / "rebase-apply").exists()


def test_push_script_refuses_paths_outside_forecasts_and_existing_files(tmp_path):
    bare = make_remote(tmp_path)
    repo = clone(tmp_path, bare, "w")
    assert push_script(repo, tmp_path, "README.md")[0].returncode == 1  # not under forecasts/
    commit_file(repo, NEW, "model,game_id\nelo,G1\n")
    (repo / NEW).write_text("model,game_id\nCHANGED,G1\n")
    assert push_script(repo, tmp_path, NEW)[0].returncode == 1  # already tracked: no edits
    assert git(bare, "log", "--format=%s", "main").splitlines() == ["c"]  # nothing was pushed


# ---- check_forecasts_append_only.sh --------------------------------------------------------------


def guard(repo, *args):
    return subprocess.run(
        ["bash", str(GUARD), *args], cwd=repo, capture_output=True, text=True, check=False
    )


def history(tmp_path):
    repo = tmp_path / "g"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit_file(repo, "forecasts/a/one.csv", "1\n", "add one")
    return repo, git(repo, "rev-parse", "HEAD")


def test_guard_allows_adding_new_forecast_files_and_other_changes(tmp_path):
    repo, base = history(tmp_path)
    commit_file(repo, "forecasts/a/two.csv", "2\n")
    commit_file(repo, "src/x.py", "print()\n")
    commit_file(repo, "src/x.py", "print(1)\n")  # editing non-forecast files is fine
    assert guard(repo, base, "HEAD").returncode == 0


def test_guard_fails_when_a_commit_modifies_an_existing_forecast(tmp_path):
    repo, base = history(tmp_path)
    commit_file(repo, "forecasts/a/one.csv", "edited\n", "edit")
    r = guard(repo, base, "HEAD")
    assert r.returncode == 1 and "forecasts/a/one.csv" in r.stdout + r.stderr


def test_guard_fails_on_rename(tmp_path):
    repo, base = history(tmp_path)
    git(repo, "mv", "forecasts/a/one.csv", "forecasts/a/renamed.csv")
    git(repo, "commit", "-q", "-m", "rename")
    assert guard(repo, base, "HEAD").returncode == 1


def test_guard_fails_on_delete(tmp_path):
    repo, base = history(tmp_path)
    git(repo, "rm", "-q", "forecasts/a/one.csv")
    git(repo, "commit", "-q", "-m", "delete")
    assert guard(repo, base, "HEAD").returncode == 1


def test_guard_sees_a_modification_hidden_by_a_later_revert(tmp_path):
    repo, base = history(tmp_path)
    commit_file(repo, "forecasts/a/one.csv", "edited\n", "edit")
    commit_file(repo, "forecasts/a/one.csv", "1\n", "revert")  # net diff is empty
    assert guard(repo, base, "HEAD").returncode == 1


def test_guard_without_a_usable_base_checks_the_whole_history(tmp_path):
    repo, _ = history(tmp_path)
    assert guard(repo, "0" * 40, "HEAD").returncode == 0
    commit_file(repo, "forecasts/a/one.csv", "edited\n", "edit")
    assert guard(repo, "0" * 40, "HEAD").returncode == 1
    assert guard(repo, "", "HEAD").returncode == 1
