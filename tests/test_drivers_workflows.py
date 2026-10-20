"""Workflow files and shell scripts around the automated NFL Drivers snapshots (spec
2026-10-19-drivers-snapshot-automation-design.md). No network: git runs against local bare repos
in tmp dirs."""

import fnmatch
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from test_forecast_workflows import clone, commit_file, git, make_remote

REPO = Path(__file__).parent.parent
PUSH = REPO / ".github" / "scripts" / "push_drivers.sh"
WORKFLOWS = REPO / ".github" / "workflows"
ACTION = REPO / ".github" / "actions" / "drivers-setup" / "action.yml"

spec = importlib.util.spec_from_file_location("drivers_gate", REPO / "jobs" / "drivers_gate.py")
dg = importlib.util.module_from_spec(spec)
sys.modules["drivers_gate"] = dg
spec.loader.exec_module(dg)
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


# ---- drivers.yml, drivers-dryrun.yml, drivers-setup ---------------------------------------------

VERIFIED = {  # tags checked with `gh api repos/<r>/git/ref/tags/<tag>` on 2026-10-19
    "actions/checkout@v7", "astral-sh/setup-uv@v10.2.0", "r-lib/actions/setup-r@v2.9.0",
    "r-lib/actions/setup-renv@v2.9.0", "actions/cache@v6.1.0",
    "./forecast-lab/.github/actions/drivers-setup",
}  # fmt: skip


def load(path):
    doc = yaml.safe_load(path.read_text())
    if True in doc:
        doc["on"] = doc.pop(True)  # YAML 1.1 reads a bare `on:` key as True
    return doc


def steps(job):
    return job["steps"]


def snapshot_job():
    return load(WORKFLOWS / "drivers.yml")["jobs"]["snapshot"]


def test_drivers_cron_equals_the_constant():
    crons = [s["cron"] for s in load(WORKFLOWS / "drivers.yml")["on"]["schedule"]]
    assert crons == [dg.DRIVERS_CRON]


def test_drivers_manual_run_has_no_inputs():
    trigger = load(WORKFLOWS / "drivers.yml")["on"]["workflow_dispatch"]
    assert not (trigger or {}).get("inputs")
    text = (WORKFLOWS / "drivers.yml").read_text()
    assert "github.event.inputs" not in text and "inputs." not in text


def test_snapshot_job_matrix_concurrency_is_per_pair_without_cancel():
    job = snapshot_job()
    assert "matrix.pair.slot" in job["concurrency"]["group"]
    assert "matrix.pair.timing" in job["concurrency"]["group"]
    assert job["concurrency"]["cancel-in-progress"] is False
    assert "fromJSON(needs.gate.outputs.pairs)" in str(job["strategy"]["matrix"]["pair"])
    assert job["strategy"]["fail-fast"] is False
    assert job["timeout-minutes"] == 40
    assert "concurrency" not in load(WORKFLOWS / "drivers.yml")  # no workflow-wide queue


def test_snapshot_job_runs_only_when_gate_found_pairs_and_alert_on_missed():
    wf = load(WORKFLOWS / "drivers.yml")
    assert wf["jobs"]["snapshot"]["needs"] == "gate"
    assert "pairs" in wf["jobs"]["snapshot"]["if"] and "[]" in wf["jobs"]["snapshot"]["if"]
    assert "missed" in wf["jobs"]["alert"]["if"]
    assert "exit 1" in wf["jobs"]["alert"]["steps"][-1]["run"]
    gate_run = " ".join(s.get("run", "") for s in wf["jobs"]["gate"]["steps"])
    assert "drivers_gate.py gate" in gate_run and "[ $? -eq 1 ]" in gate_run
    checkout = wf["jobs"]["gate"]["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0  # commit times of snapshots need full history


def test_every_step_after_check_is_gated_on_run():
    st = steps(snapshot_job())
    i = next(n for n, s in enumerate(st) if "drivers_gate.py check" in s.get("run", ""))
    assert st[i]["id"] == "check"
    for s in st[i + 1 :]:
        assert "steps.check.outputs.run == 'true'" in s.get("if", ""), s


def test_pytest_unpiped_and_ruff_before_push():
    runs = [s.get("run", "") for s in steps(snapshot_job())]
    order = [next(n for n, r in enumerate(runs) if key in r)
             for key in ("run.R", "snapshot_drivers.py", "pytest -q", "ruff check .", "push_drivers.sh")]  # fmt: skip
    assert order == sorted(order) and order[-1] == len(runs) - 1
    pytest_line = runs[order[2]]
    assert "|" not in pytest_line and "PYTHON_DOTENV_DISABLED=1" in pytest_line


def test_snapshot_log_is_written_outside_the_checkout():
    run = next(s["run"] for s in steps(snapshot_job()) if "snapshot_drivers.py" in s.get("run", ""))
    assert "--slot" in run and "--timing" in run and "RUNNER_TEMP" in run
    assert "wrote" in run  # the snapshot dir is parsed from the job's `wrote ...` line


def test_checkouts_are_siblings():
    for job in ("gate", "snapshot"):
        co = load(WORKFLOWS / "drivers.yml")["jobs"][job]["steps"][0]
        assert co["uses"] == "actions/checkout@v7" and co["with"]["path"] == "forecast-lab"
        assert co["with"]["ref"] == "main"
    co = next(s for s in load(ACTION)["runs"]["steps"] if s.get("uses") == "actions/checkout@v7")
    assert co["with"]["repository"] == "noah-olivieri/nfl-drivers"
    assert co["with"]["path"] == "nfl-drivers" and co["with"]["ref"] == "master"


def cache_globs():
    st = next(s for s in load(ACTION)["runs"]["steps"] if s.get("uses") == "actions/cache@v6.1.0")
    return st, [g.strip() for g in st["with"]["path"].splitlines() if g.strip()]


def test_nflverse_cache_covers_2006_2025_and_never_2026():
    st, globs = cache_globs()
    def hit(name):
        return any(fnmatch.fnmatch(f"nfl-drivers/data/cache/{name}", g) for g in globs)
    assert not hit("pbp_2026.rds") and not hit("schedules_2026.rds") and not hit("results.rds")
    assert all(hit(f"pbp_{y}.rds") for y in range(2006, 2026))
    assert all(hit(f"schedules_{y}.rds") for y in range(2009, 2026))
    assert st["with"]["key"] == "nflverse-2006-2025-v1"


def test_setup_pins_r_from_renv_lock_and_uses_binaries():
    text = ACTION.read_text()
    assert "renv.lock" in text and "use-public-rspm: true" in text
    assert "RENV_CONFIG_REPOS_OVERRIDE" in text and "packagemanager.posit.co" in text
    renv = next(s for s in load(ACTION)["runs"]["steps"] if "setup-renv" in s.get("uses", ""))
    assert renv["with"]["working-directory"] == "nfl-drivers"


def test_dryrun_never_pushes():
    wf = load(WORKFLOWS / "drivers-dryrun.yml")
    assert wf["permissions"] == {"contents": "read"}
    assert set(wf["on"]) == {"workflow_dispatch"}
    assert "push_" not in (WORKFLOWS / "drivers-dryrun.yml").read_text()
    assert "git push" not in (WORKFLOWS / "drivers-dryrun.yml").read_text()


def test_drivers_workflow_has_write_permission_only_for_contents():
    assert load(WORKFLOWS / "drivers.yml")["permissions"] == {"contents": "write"}


def test_drivers_action_versions_are_the_verified_ones():
    used = set()
    for path in (WORKFLOWS / "drivers.yml", WORKFLOWS / "drivers-dryrun.yml", ACTION):
        used |= set(re.findall(r"uses:\s*(\S+)", path.read_text()))
    assert used <= VERIFIED, used - VERIFIED


def test_setup_fails_fast_if_nfl_drivers_tree_is_not_clean():
    last = load(ACTION)["runs"]["steps"][-1]
    assert "git -C nfl-drivers status --porcelain" in last["run"] and "exit 1" in last["run"]


def test_r_jobs_pin_the_runner_image():
    # ubuntu-latest moves to Ubuntu 26 from 2026-10-19: the renv cache key and Posit binaries
    # are per OS release, so an unplanned move would rebuild packages from source mid-window.
    assert snapshot_job()["runs-on"] == "ubuntu-24.04"
    assert load(WORKFLOWS / "drivers-dryrun.yml")["jobs"]["dryrun"]["runs-on"] == "ubuntu-24.04"
