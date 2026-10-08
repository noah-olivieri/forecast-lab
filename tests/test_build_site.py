import csv
import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from lab import forecasts as lab_forecasts
from lab.ingest.common import SNAPSHOT_SCHEMA

spec = importlib.util.spec_from_file_location(
    "build_site", Path(__file__).parent.parent / "jobs" / "build_site.py"
)
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)

KICKOFF = datetime(2026, 10, 9, 0, 15, tzinfo=UTC)  # TB at DAL, Thu 10/8 8:15 PM ET
SNAP = datetime(2026, 10, 7, 17, 18, 20, tzinfo=UTC)
NOW = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)
GAMES = [
    {"game_id": "2026_05_TB_DAL", "away": "TB", "home": "DAL", "kickoff_utc": "2026-10-09T00:15:00Z"},
    {"game_id": "2026_05_PHI_JAX", "away": "PHI", "home": "JAX", "kickoff_utc": "2026-10-11T13:30:00Z"},
    {"game_id": "2026_05_CHI_GB", "away": "CHI", "home": "GB", "kickoff_utc": "2026-10-11T17:00:00Z"},
]
FEES = {"series": "KXNFLGAME", "fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1.0}


def sh(root: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(root),
    }  # fmt: skip
    r = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=root, env=env, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return r.stdout.strip()


def snapshot_frame(rows: list[dict]) -> pl.DataFrame:
    full = [{c: None for c in SNAPSHOT_SCHEMA} | {"ts_utc": SNAP, "kind": "winner"} | r for r in rows]
    return pl.DataFrame(full, schema=SNAPSHOT_SCHEMA)


def write_forecast(path: Path, created: str = "2026-10-07T17:20:00Z", kickoff=KICKOFF) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = {
        "git_sha": "abc", "venue": "kalshi", "market_ticker": "KXNFLGAME-26OCT08TBDAL-DAL",
        "game_id": "2026_05_TB_DAL", "yes_team": "DAL", "prices_flipped": "False",
        "as_of_ts": "2026-10-07T17:18:20Z", "created_ts": created,
        "kickoff_ts": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market_yes_bid": "0.79", "market_yes_ask": "0.8", "snapshot_ts": "2026-10-07T17:18:20Z",
    }  # fmt: skip
    rows = [
        {**base, "model": "elo", "model_version": "elo-538-default-v0", "p_yes": "0.71"},
        {**base, "model": "home_rate", "model_version": "home-rate-v0", "p_yes": "0.55"},
        {**base, "model": "market_mid", "model_version": "market-mid-v0", "p_yes": "0.795"},
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(base) + ["model", "model_version", "p_yes"])
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def repo(tmp_path):
    """A repo with a kickoff schedule, a `main` that mirrors origin/main, and a `data` branch."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "kickoffs.json").write_text(json.dumps(GAMES))
    (root / "forecasts").mkdir()
    (root / "forecasts" / ".gitkeep").write_text("")
    sh(root, "init", "-q", "-b", "main")
    sh(root, "add", "config", "forecasts")
    sh(root, "commit", "-q", "-m", "base")
    sh(root, "update-ref", "refs/remotes/origin/main", "HEAD")

    # Orphan data branch holding one snapshot per venue, written with plumbing so the work tree
    # is never touched (same rule as the real job: read with `git show`).
    kalshi = snapshot_frame([
        {"venue": "kalshi", "market_ticker": "KXNFLGAME-26OCT08TBDAL-DAL", "subtitle": "Dallas",
         "yes_bid": 0.79, "yes_ask": 0.80},
        {"venue": "kalshi", "market_ticker": "KXNFLGAME-26OCT11PHIJAC-JAC", "subtitle": "Jacksonville",
         "yes_bid": 0.0, "yes_ask": 1.0},
        {"venue": "kalshi", "market_ticker": "KXNFLSPREAD-26OCT08TBDAL-DAL3", "kind": "spread",
         "yes_bid": 0.5, "yes_ask": 0.51},
        {"venue": "kalshi", "market_ticker": "KXNFLGAME-26OCT11CHIGB-GB", "subtitle": "Green Bay",
         "yes_bid": 0.41, "yes_ask": 0.42},
    ])  # fmt: skip
    poly = snapshot_frame([
        {"venue": "polymarket_us", "market_ticker": "aec-nfl-tb-dal-2026-10-08",
         "subtitle": "Buccaneers", "yes_bid": 0.2025, "yes_ask": 0.205},
        # Polymarket lists the away side (Bears 55-56c), so the home price is 44-45c: above Kalshi's ask.
        {"venue": "polymarket_us", "market_ticker": "aec-nfl-chi-gb-2026-10-11",
         "subtitle": "Bears", "yes_bid": 0.55, "yes_ask": 0.56},
    ])  # fmt: skip
    older = snapshot_frame([
        {"venue": "kalshi", "market_ticker": "KXNFLGAME-26OCT08TBDAL-DAL", "subtitle": "Dallas",
         "yes_bid": 0.5, "yes_ask": 0.6},
    ]).with_columns(pl.lit(datetime(2026, 10, 7, 9, 57, tzinfo=UTC)).alias("ts_utc"))
    tmp = tmp_path / "blobs"
    tmp.mkdir()
    entries = []
    for name, df in {
        "20261007T1718Z_kalshi.parquet": kalshi,
        "20261007T1718Z_polymarket_us.parquet": poly,
        "20261007T0957Z_kalshi.parquet": older,
    }.items():
        df.write_parquet(tmp / name)
        blob = sh(root, "hash-object", "-w", str(tmp / name))
        entries.append(f"100644 blob {blob}\t{name}")
    mk = subprocess.run(
        ["git", "mktree"], cwd=root, input="\n".join(entries) + "\n", capture_output=True, text=True, check=True
    ).stdout.strip()  # fmt: skip
    # nest under snapshots/hourly/
    sub = subprocess.run(["git", "mktree"], cwd=root, input=f"040000 tree {mk}\thourly\n",
                         capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    top = subprocess.run(["git", "mktree"], cwd=root, input=f"040000 tree {sub}\tsnapshots\n",
                         capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    commit = sh(root, "commit-tree", top, "-m", "snapshots")
    sh(root, "update-ref", "refs/remotes/origin/data", commit)
    return root


def run(root: Path, tmp_path: Path, fees=FEES) -> dict:
    out = tmp_path / "out"
    bs.build(root, out, now=NOW, fees_fn=lambda: fees)  # never reaches the Kalshi API
    return {p.stem: json.loads(p.read_text()) for p in out.glob("*.json")}


# --- market prices ---------------------------------------------------------------------------


def test_prices_come_from_newest_snapshot_with_its_timestamp(repo, tmp_path):
    d = run(repo, tmp_path)
    assert d["market"]["snapshots"] == {
        "kalshi": "2026-10-07T17:18:20Z",
        "polymarket_us": "2026-10-07T17:18:20Z",
    }
    q = d["market"]["games"]["2026_05_TB_DAL"]
    assert q["kalshi"]["bid"] == 79.0 and q["kalshi"]["ask"] == 80.0  # not the older 50/60 file
    assert d["meta"]["snapshots"] == d["market"]["snapshots"]


def test_polymarket_away_side_is_flipped_to_home(repo, tmp_path):
    p = run(repo, tmp_path)["market"]["games"]["2026_05_TB_DAL"]["polymarket_us"]
    assert p["flipped"] is True
    assert p["bid"] == 79.5 and p["ask"] == 79.75  # 100 - 20.5 and 100 - 20.25


def test_empty_book_has_no_bid_or_ask(repo, tmp_path):
    q = run(repo, tmp_path)["market"]["games"]["2026_05_PHI_JAX"]["kalshi"]
    assert q["ticker"] == "KXNFLGAME-26OCT11PHIJAC-JAC"  # Kalshi spells Jacksonville JAC
    assert q["bid"] is None and q["ask"] is None


def test_no_data_branch_gives_empty_market(repo, tmp_path):
    sh(repo, "update-ref", "-d", "refs/remotes/origin/data")
    d = run(repo, tmp_path)
    assert d["market"]["snapshots"] == {} and d["market"]["games"] == {}
    assert d["meta"]["data_commit"] is None


def test_local_data_branch_is_used_when_origin_is_missing(repo, tmp_path):
    sha = sh(repo, "rev-parse", "refs/remotes/origin/data")
    sh(repo, "update-ref", "refs/heads/data", sha)
    sh(repo, "update-ref", "-d", "refs/remotes/origin/data")
    assert run(repo, tmp_path)["market"]["snapshots"]["kalshi"] == "2026-10-07T17:18:20Z"


def test_clean_side_and_flip():
    assert bs.clean_side(0.0, 1.0) == (None, None)
    assert bs.clean_side(0.2, 0.25) == (0.2, 0.25)
    assert bs.home_quote({"yes_bid": 0.2025, "yes_ask": 0.205}, flip=True) == (79.5, 79.75)
    assert bs.home_quote({"yes_bid": 0.0, "yes_ask": 0.3}, flip=True) == (70.0, None)
    assert bs.home_quote(None, flip=False) is None


def test_ticker_and_name_helpers_match_the_forecast_logger():
    """Duplicated helpers must give the same keys the logger writes into forecast CSVs."""
    assert bs.NICKNAMES == lab_forecasts.NICKNAMES
    assert bs.KALSHI_CODE == lab_forecasts._KALSHI_CODE
    for away, home, when in [
        ("TB", "DAL", KICKOFF),
        ("PHI", "JAX", datetime(2026, 10, 11, 13, 30, tzinfo=UTC)),
        ("SF", "LA", datetime(2026, 9, 11, 0, 35, tzinfo=UTC)),
    ]:
        want = lab_forecasts._tickers(away, home, when.astimezone(bs.ET))
        assert (bs.kalshi_ticker(away, home, when), bs.polymarket_ticker(away, home, when)) == want


# --- forecasts and the ticker dot ------------------------------------------------------------


def test_no_forecast_files_means_no_dot(repo, tmp_path):
    d = run(repo, tmp_path)
    assert d["meta"]["games_logged"] == 0 and d["meta"]["forecast_files"] == 0
    assert not any(g["logged"] for g in d["games"])
    assert all(g["model"] is None for g in d["games"])
    assert d["forecasts"] == {"files": [], "rows": []}


def commit_forecast(repo: Path, created="2026-10-07T17:20:00Z", on_main=True) -> Path:
    path = repo / "forecasts" / "2026-10-08" / "nfl_2026-10-07T17-18Z.csv"
    write_forecast(path, created=created)
    sh(repo, "add", str(path.relative_to(repo)))
    sh(repo, "commit", "-q", "-m", "forecast")
    if on_main:
        sh(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return path


def test_pushed_forecast_before_kickoff_gets_the_dot_and_model(repo, tmp_path):
    commit_forecast(repo)
    d = run(repo, tmp_path)
    tb = next(g for g in d["games"] if g["id"] == "2026_05_TB_DAL")
    assert tb["logged"] is True
    assert tb["model"]["p_home"] == 71.0 and tb["model"]["name"] == "elo-538-default-v0"
    assert next(g for g in d["games"] if g["id"] == "2026_05_PHI_JAX")["logged"] is False
    assert d["meta"]["games_logged"] == 1
    f = d["forecasts"]["files"][0]
    assert f["status"] == "pushed" and f["rows"] == 3
    assert f["commit_url"].endswith(f"/commit/{f['commit']}")
    assert f["blob_url"].endswith(f"/blob/{f['commit']}/{f['path']}")
    mid = next(r for r in d["forecasts"]["rows"] if r["model"] == "market_mid")
    assert (mid["market_bid"], mid["market_ask"]) == (79.0, 80.0)


def test_committed_but_unpushed_forecast_gets_no_dot(repo, tmp_path):
    base = sh(repo, "rev-parse", "HEAD")
    commit_forecast(repo, on_main=False)
    assert sh(repo, "rev-parse", "refs/remotes/origin/main") == base
    d = run(repo, tmp_path)
    assert d["forecasts"]["files"][0]["status"] == "committed"
    assert d["meta"]["games_logged"] == 0
    assert all(not g["logged"] for g in d["games"])


def test_untracked_forecast_gets_no_dot(repo, tmp_path):
    write_forecast(repo / "forecasts" / "2026-10-08" / "nfl_x.csv")
    d = run(repo, tmp_path)
    f = d["forecasts"]["files"][0]
    assert f["status"] == "uncommitted" and f["commit"] is None and f["blob_url"] is None
    assert d["meta"]["games_logged"] == 0


def test_forecast_created_after_kickoff_gets_no_dot(repo, tmp_path):
    commit_forecast(repo, created="2026-10-09T00:30:00Z")
    d = run(repo, tmp_path)
    assert all(r["before_kickoff"] is False for r in d["forecasts"]["rows"])
    assert d["meta"]["games_logged"] == 0
    assert next(g for g in d["games"] if g["id"] == "2026_05_TB_DAL")["model"] is None


def test_bad_csv_is_reported_and_skipped(repo, tmp_path):
    (repo / "forecasts" / "bad.csv").write_text("a,b\n1,2\n")
    d = run(repo, tmp_path)
    assert d["forecasts"]["files"] == []
    assert any("bad.csv" in p and "missing columns" in p for p in d["meta"]["problems"])


def test_missing_origin_main_is_reported(repo, tmp_path):
    sh(repo, "update-ref", "-d", "refs/remotes/origin/main")
    commit_forecast(repo, on_main=False)
    d = run(repo, tmp_path)
    assert d["meta"]["games_logged"] == 0
    assert any("origin/main" in p for p in d["meta"]["problems"])


# --- games, locks, meta ----------------------------------------------------------------------


def test_games_carry_week_lock_time_and_sort_by_kickoff(repo, tmp_path):
    games = run(repo, tmp_path)["games"]
    assert [g["id"] for g in games] == ["2026_05_TB_DAL", "2026_05_PHI_JAX", "2026_05_CHI_GB"]
    tb = games[0]
    assert tb["week"] == 5
    assert tb["lock_utc"] == "2026-10-08T00:15:00Z"  # 24h before kickoff
    assert tb["kickoff_utc"] == "2026-10-09T00:15:00Z"


def test_meta_has_build_time_and_commit_links(repo, tmp_path):
    meta = run(repo, tmp_path)["meta"]
    assert meta["built_utc"] == "2026-10-07T18:00:00Z"
    assert meta["commit"] == sh(repo, "rev-parse", "HEAD")
    assert meta["commit_url"] == f"{bs.REPO_URL}/commit/{meta['commit']}"
    assert meta["data_commit"] == sh(repo, "rev-parse", "refs/remotes/origin/data")


def test_build_never_writes_outside_the_output_dir(repo, tmp_path):
    before = sh(repo, "status", "--porcelain")
    run(repo, tmp_path)
    assert sh(repo, "status", "--porcelain") == before
    assert sorted(p.name for p in (repo / "forecasts").iterdir()) == [".gitkeep"]


# --- cross-venue gap and Kalshi fees ---------------------------------------------------------

RATE = bs.kalshi_taker_rate(FEES)


def quote(k_bid, k_ask, p_bid, p_ask):
    return {
        "kalshi": {"ticker": "k", "bid": k_bid, "ask": k_ask},
        "polymarket_us": {"ticker": "p", "bid": p_bid, "ask": p_ask, "flipped": False},
    }


def test_kalshi_fee_formula():
    assert RATE == pytest.approx(0.07)
    assert bs.kalshi_fee_cents(50, RATE) == pytest.approx(1.75)  # the schedule's 1.75c maximum
    assert bs.kalshi_fee_cents(20, RATE) == pytest.approx(1.12)
    assert bs.kalshi_taker_rate({**FEES, "fee_multiplier": 0.5}) == pytest.approx(0.035)
    assert bs.kalshi_taker_rate({"fee_type": "flat", "fee_multiplier": 1}) is None
    assert bs.kalshi_taker_rate(None) is None


def test_overlapping_or_touching_ranges_have_no_gap():
    assert bs.cross_gap(quote(79, 80, 79.5, 79.75), RATE) is None  # nested
    assert bs.cross_gap(quote(79, 80, 78.5, 79.5), RATE) is None  # partial overlap
    assert bs.cross_gap(quote(79, 80, 80, 81), RATE) is None  # kalshi ask == poly bid: gross 0


def test_gap_poly_cheaper_sell_on_kalshi():
    c = bs.cross_gap(quote(60, 61, 59.25, 59.5), RATE)
    assert (c["buy"], c["buy_price"], c["sell"], c["sell_price"]) == ("polymarket_us", 59.5, "kalshi", 60)
    assert c["gross"] == 0.5
    assert c["kalshi_fee"] == pytest.approx(0.07 * 0.6 * 0.4 * 100, abs=1e-3)  # fee on the 60c leg
    assert c["net"] == pytest.approx(0.5 - 1.68, abs=1e-3) and c["survives"] is False


def test_gap_kalshi_cheaper_sell_on_poly_and_can_survive():
    c = bs.cross_gap(quote(41, 42, 44, 45), RATE)
    assert (c["buy"], c["sell"], c["gross"]) == ("kalshi", "polymarket_us", 2.0)
    assert c["kalshi_fee"] == pytest.approx(0.07 * 0.42 * 0.58 * 100, abs=1e-3)  # fee on the 42c leg
    assert c["net"] == pytest.approx(2.0 - 1.7052, abs=1e-3) and c["survives"] is True


def test_gap_without_fee_data_has_no_net():
    c = bs.cross_gap(quote(41, 42, 44, 45), None)
    assert c["gross"] == 2.0 and c["kalshi_fee"] is None and c["net"] is None and c["survives"] is None


def test_gap_needs_two_sided_quotes_on_both_venues():
    assert bs.cross_gap(quote(None, 42, 44, 45), RATE) is None
    assert bs.cross_gap(quote(41, 42, 44, None), RATE) is None
    assert bs.cross_gap({"kalshi": {"bid": 41, "ask": 42}}, RATE) is None


def test_build_writes_cross_gap_only_for_games_that_have_one(repo, tmp_path):
    m = run(repo, tmp_path)["market"]
    assert "cross" not in m["games"]["2026_05_TB_DAL"]  # nested ranges
    c = m["games"]["2026_05_CHI_GB"]["cross"]
    assert c["buy"] == "kalshi" and c["sell"] == "polymarket_us" and c["gross"] == 2.0
    assert c["survives"] is True
    assert m["fees"]["kalshi"]["taker_rate"] == pytest.approx(0.07)
    assert m["fees"]["kalshi"]["fetched_utc"] == "2026-10-07T18:00:00Z"


def test_build_without_fee_data_keeps_gross_and_reports_it(repo, tmp_path):
    d = run(repo, tmp_path, fees=None)
    c = d["market"]["games"]["2026_05_CHI_GB"]["cross"]
    assert c["gross"] == 2.0 and c["net"] is None
    assert d["market"]["fees"] == {"kalshi": None}
    assert any("fee data unavailable" in p for p in d["meta"]["problems"])


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise bs.httpx.HTTPStatusError("bad", request=None, response=None)

    def json(self):
        return self.payload


def test_fetch_kalshi_fees_reads_series_metadata(monkeypatch):
    seen = {}

    def fake_get(url, **kw):
        seen["url"] = url
        return FakeResponse({"series": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1}})

    monkeypatch.setattr(bs.httpx, "get", fake_get)
    assert bs.fetch_kalshi_fees() == FEES
    assert seen["url"].endswith("/series/KXNFLGAME")


@pytest.mark.parametrize(
    "result",
    [bs.httpx.ConnectError("down"), FakeResponse({}, status=500), FakeResponse({"series": {}})],
)
def test_fetch_kalshi_fees_fails_soft(monkeypatch, result):
    def fake_get(url, **kw):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(bs.httpx, "get", fake_get)
    assert bs.fetch_kalshi_fees() is None
