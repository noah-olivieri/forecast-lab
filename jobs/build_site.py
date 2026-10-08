"""Write site/data/*.json for the static site (GitHub Pages). Read-only: it never writes to
forecasts/, config/ or any branch.

    build_site.py [--out site/data] [--forecasts forecasts] [--now ISO]

Inputs
  * forecasts/**/*.csv      the only source of "forecast logged" (PLAN 7a). A game counts as logged
                            only if its CSV was committed, that commit is on origin/main, and
                            created_ts is before the CSV's kickoff_ts.
  * config/kickoffs.json    the NFL schedule the collector uses.
  * newest snapshot per venue on the `data` branch, read with `git show <ref>:<path>` (no
    checkout, no work tree). `origin/data` is preferred over a local `data` branch.

Outputs: meta.json, games.json, market.json, forecasts.json. Prices are cents for the YES side
of the home team, so the market and the model share one axis.

Cross-venue gap: when one venue's bid is above the other's ask, market.json carries the gross
cents per contract and, if Kalshi's fee metadata could be fetched, the same after an estimated
Kalshi taker fee. Paper only; order size is not checked.

No secrets are read: this module deliberately does not import `lab.config` (which loads .env).
The ticker and Polymarket naming helpers are duplicated from `lab.forecasts`; a test pins them
to the originals so they cannot drift.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import polars as pl

from lab.ingest.common import USER_AGENT
from lab.store.snapshots import parse_hourly

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/noah-olivieri/forecast-lab"
ET = ZoneInfo("America/New_York")
LOCK_BEFORE = timedelta(hours=24)  # the T-24h forecast
MAIN_REF = "origin/main"
DATA_REFS = ("origin/data", "data")
VENUES = ("kalshi", "polymarket_us")
SNAPSHOT_COLUMNS = ["ts_utc", "market_ticker", "kind", "subtitle", "yes_bid", "yes_ask", "status"]
REQUIRED_COLUMNS = {
    "model", "model_version", "venue", "game_id", "yes_team", "p_yes", "created_ts", "kickoff_ts",
    "as_of_ts", "snapshot_ts", "market_yes_bid", "market_yes_ask", "market_ticker", "git_sha",
}  # fmt: skip
HEADLINE_MODEL = "elo"
KALSHI_API = "https://external-api.kalshi.com/trade-api/v2"
KALSHI_SERIES = "KXNFLGAME"
# Taker fee = ceil(KALSHI_FEE_COEFF x fee_multiplier x C x P x (1-P)) dollars for C contracts at
# price P, on `quadratic*` series (published fee schedule). fee_type and fee_multiplier are read
# from the API, not stored here.
KALSHI_FEE_COEFF = 0.07

# Kalshi spells two codes differently from nflverse.
KALSHI_CODE = {"JAX": "JAC", "LA": "LAR"}
NICKNAMES = {
    "49ers": "SF", "Bears": "CHI", "Bengals": "CIN", "Bills": "BUF", "Broncos": "DEN",
    "Browns": "CLE", "Buccaneers": "TB", "Cardinals": "ARI", "Chargers": "LAC",
    "Chiefs": "KC", "Colts": "IND", "Commanders": "WAS", "Cowboys": "DAL",
    "Dolphins": "MIA", "Eagles": "PHI", "Falcons": "ATL", "Giants": "NYG",
    "Jaguars": "JAX", "Jets": "NYJ", "Lions": "DET", "Packers": "GB", "Panthers": "CAR",
    "Patriots": "NE", "Raiders": "LV", "Rams": "LA", "Ravens": "BAL", "Saints": "NO",
    "Seahawks": "SEA", "Steelers": "PIT", "Texans": "HOU", "Titans": "TEN", "Vikings": "MIN",
}  # fmt: skip


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


# --- git -------------------------------------------------------------------------------------


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=check)


def git_text(root: Path, *args: str) -> str:
    return git(root, *args).stdout.decode().strip()


def ref_exists(root: Path, ref: str) -> bool:
    return git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False).returncode == 0


def data_ref(root: Path) -> str | None:
    return next((r for r in DATA_REFS if ref_exists(root, r)), None)


# --- market prices from the data branch ------------------------------------------------------


def newest_snapshots(root: Path, ref: str) -> dict[str, tuple[datetime, str]]:
    """Newest hourly file per venue on `ref`: {venue: (capture time, path in the tree)}."""
    listing = git_text(root, "ls-tree", "-r", "--name-only", ref, "--", "snapshots/hourly/")
    best: dict[str, tuple[datetime, str]] = {}
    for path in listing.splitlines():
        parsed = parse_hourly(path)
        if parsed and (parsed[1] not in best or parsed[0] > best[parsed[1]][0]):
            best[parsed[1]] = (parsed[0], path)
    return best


def read_snapshot(root: Path, ref: str, path: str) -> pl.DataFrame:
    blob = git(root, "show", f"{ref}:{path}").stdout
    df = pl.read_parquet(io.BytesIO(blob))
    return df.select([c for c in SNAPSHOT_COLUMNS if c in df.columns])


def kalshi_ticker(away: str, home: str, kickoff: datetime) -> str:
    d = kickoff.astimezone(ET)
    ka, kh = KALSHI_CODE.get(away, away), KALSHI_CODE.get(home, home)
    return f"KXNFLGAME-{d:%y}{d:%b}{d:%d}".upper() + f"{ka}{kh}-{kh}"


def polymarket_ticker(away: str, home: str, kickoff: datetime) -> str:
    return f"aec-nfl-{away.lower()}-{home.lower()}-{kickoff.astimezone(ET):%Y-%m-%d}"


def clean_side(bid: float | None, ask: float | None) -> tuple[float | None, float | None]:
    """Venue dollars -> usable bid/ask. A 0 bid is an empty book and a 1.00 ask is no offer."""
    return (
        None if bid is None or bid <= 0 else bid,
        None if ask is None or ask >= 1 else ask,
    )


def cents(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 4)


def home_quote(
    row: dict | None, flip: bool
) -> tuple[float | None, float | None] | None:
    """Home-team YES bid/ask in cents, or None if the venue has no row."""
    if row is None:
        return None
    bid, ask = clean_side(row.get("yes_bid"), row.get("yes_ask"))
    if flip:
        bid, ask = (None if ask is None else 1 - ask), (None if bid is None else 1 - bid)
    return cents(bid), cents(ask)


def fetch_kalshi_fees(series: str = KALSHI_SERIES, timeout: float = 10.0) -> dict | None:
    """fee_type and fee_multiplier for `series` from the Kalshi API (keyless), or None."""
    try:
        r = httpx.get(
            f"{KALSHI_API}/series/{series}", headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
        r.raise_for_status()
        info = r.json()["series"]
        return {
            "series": series,
            "fee_type": str(info["fee_type"]),
            "fee_multiplier": float(info["fee_multiplier"]),
        }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        print(f"warning: no Kalshi fee data ({e!r})", file=sys.stderr)
        return None


def kalshi_taker_rate(fees: dict | None) -> float | None:
    """Coefficient in fee = rate x P x (1-P) per contract, or None if the fee type is unknown."""
    if not fees or not str(fees.get("fee_type", "")).startswith("quadratic"):
        return None
    return KALSHI_FEE_COEFF * float(fees["fee_multiplier"])


def kalshi_fee_cents(price_cents: float, rate: float) -> float:
    """Estimated taker fee in cents per contract at `price_cents`, before whole-cent rounding."""
    p = price_cents / 100
    return rate * p * (1 - p) * 100


def cross_gap(entry: dict, rate: float | None) -> dict | None:
    """Gross arbitrage between the two venues' home-team YES quotes, if their bid-ask ranges
    do not overlap: buy YES at one venue's ask, sell it at the other's higher bid.

    Net subtracts the estimated Kalshi taker fee on the Kalshi leg only. Polymarket US fees are
    not counted, so a positive net is an upper bound; a non-positive net is final.
    """
    k, p = entry.get("kalshi"), entry.get("polymarket_us")
    if not k or not p or None in (k["bid"], k["ask"], p["bid"], p["ask"]):
        return None
    for buy, sell, ask, bid in (
        ("polymarket_us", "kalshi", p["ask"], k["bid"]),
        ("kalshi", "polymarket_us", k["ask"], p["bid"]),
    ):
        gross = round(bid - ask, 4)
        if gross <= 0:
            continue
        kalshi_price = bid if sell == "kalshi" else ask
        fee = None if rate is None else round(kalshi_fee_cents(kalshi_price, rate), 4)
        net = None if fee is None else round(gross - fee, 4)
        return {
            "buy": buy, "buy_price": ask, "sell": sell, "sell_price": bid,
            "gross": gross, "kalshi_fee": fee, "net": net,
            "survives": None if net is None else net > 0,
        }  # fmt: skip
    return None


def build_market(
    root: Path, games: list[dict], fee_rate: float | None = None
) -> tuple[dict, dict[str, dict]]:
    """(snapshot times, {game_id: {venue: quote}}) from the newest data-branch snapshots."""
    ref = data_ref(root)
    if ref is None:
        print("warning: no data branch (origin/data or data); market.json will be empty")
        return {}, {}
    newest = newest_snapshots(root, ref)
    frames: dict[str, dict[str, dict]] = {}
    stamps: dict[str, str] = {}
    for venue in VENUES:
        if venue not in newest:
            continue
        ts, path = newest[venue]
        df = read_snapshot(root, ref, path).filter(pl.col("kind") == "winner")
        frames[venue] = {r["market_ticker"]: r for r in df.to_dicts()}
        # The file's own row timestamps are the capture time; the file name is the fallback.
        stamps[venue] = iso(df["ts_utc"].max() if df.height else ts)

    quotes: dict[str, dict] = {}
    for g in games:
        kick = parse_ts(g["kickoff_utc"])
        entry = {}
        k_ticker = kalshi_ticker(g["away"], g["home"], kick)
        k_row = frames.get("kalshi", {}).get(k_ticker)
        k = home_quote(k_row, flip=False)
        if k is not None:
            entry["kalshi"] = {"ticker": k_ticker, "bid": k[0], "ask": k[1]}
        p_ticker = polymarket_ticker(g["away"], g["home"], kick)
        p_row = frames.get("polymarket_us", {}).get(p_ticker)
        if p_row is not None:
            yes_team = NICKNAMES.get(p_row.get("subtitle"))
            if yes_team in (g["home"], g["away"]):
                flipped = yes_team == g["away"]
                p = home_quote(p_row, flip=flipped)
                entry["polymarket_us"] = {
                    "ticker": p_ticker, "bid": p[0], "ask": p[1], "flipped": flipped,
                }  # fmt: skip
        if entry:
            cross = cross_gap(entry, fee_rate)
            if cross:
                entry["cross"] = cross
            quotes[g["id"]] = entry
    return stamps, quotes


# --- forecasts -------------------------------------------------------------------------------


def file_commit(root: Path, rel: str) -> dict | None:
    """The commit that first added `rel`, and whether origin/main contains it."""
    out = git_text(root, "log", "--diff-filter=A", "--format=%H\t%cI", "--", rel)
    if not out:
        return None
    sha, when = out.splitlines()[-1].split("\t")
    on_main = (
        ref_exists(root, MAIN_REF)
        and git(root, "merge-base", "--is-ancestor", sha, MAIN_REF, check=False).returncode == 0
    )
    return {"sha": sha, "ts": iso(datetime.fromisoformat(when)), "on_main": on_main}


def _num(s: str) -> float | None:
    return float(s) if s not in ("", None) else None


def read_forecasts(root: Path, forecasts_dir: Path) -> tuple[list[dict], list[dict], list[str]]:
    """(files, flattened rows, problems). Bad files are reported, not silently dropped."""
    files, rows, problems = [], [], []
    for path in sorted(forecasts_dir.glob("**/*.csv")):
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name
        try:
            with path.open(newline="") as f:
                reader = csv.DictReader(f)
                missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
                if missing:
                    raise ValueError(f"missing columns {sorted(missing)}")
                body = list(reader)
            parsed = [
                {
                    "game_id": r["game_id"], "model": r["model"], "model_version": r["model_version"],
                    "venue": r["venue"], "market_ticker": r["market_ticker"],
                    "yes_team": r["yes_team"], "git_sha": r["git_sha"],
                    "p_yes": round(float(r["p_yes"]) * 100, 4),
                    "market_bid": cents(_num(r["market_yes_bid"])),
                    "market_ask": cents(_num(r["market_yes_ask"])),
                    "created_ts": iso(parse_ts(r["created_ts"])),
                    "as_of_ts": iso(parse_ts(r["as_of_ts"])),
                    "snapshot_ts": iso(parse_ts(r["snapshot_ts"])),
                    "kickoff_ts": iso(parse_ts(r["kickoff_ts"])),
                }
                for r in body
            ]  # fmt: skip
        except (OSError, ValueError, KeyError) as e:
            problems.append(f"{rel}: {e}")
            continue
        commit = file_commit(root, rel)
        status = "uncommitted" if commit is None else ("pushed" if commit["on_main"] else "committed")
        for r in parsed:
            r["file"] = rel
            r["before_kickoff"] = r["created_ts"] < r["kickoff_ts"]
        files.append({
            "path": rel, "rows": len(parsed), "status": status,
            "commit": commit["sha"] if commit else None,
            "commit_ts": commit["ts"] if commit else None,
            "blob_url": f"{REPO_URL}/blob/{commit['sha']}/{rel}" if commit else None,
            "commit_url": f"{REPO_URL}/commit/{commit['sha']}" if commit else None,
        })  # fmt: skip
        rows.extend(parsed)
    return files, rows, problems


# --- assemble --------------------------------------------------------------------------------


def week_of(game_id: str) -> int | None:
    parts = game_id.split("_")
    return int(parts[1]) if len(parts) > 2 and parts[1].isdigit() else None


def build_games(kickoffs: list[dict], files: list[dict], rows: list[dict]) -> list[dict]:
    status = {f["path"]: f["status"] for f in files}
    counted: dict[str, list[dict]] = {}
    for r in rows:
        if status.get(r["file"]) == "pushed" and r["before_kickoff"]:
            counted.setdefault(r["game_id"], []).append(r)
    games = []
    for k in sorted(kickoffs, key=lambda k: (k["kickoff_utc"], k["game_id"])):
        kick = parse_ts(k["kickoff_utc"])
        mine = counted.get(k["game_id"], [])
        headline = [r for r in mine if r["model"] == HEADLINE_MODEL]
        latest = max(headline, key=lambda r: r["created_ts"]) if headline else None
        games.append({
            "id": k["game_id"], "week": week_of(k["game_id"]), "away": k["away"], "home": k["home"],
            "kickoff_utc": iso(kick), "lock_utc": iso(kick - LOCK_BEFORE),
            "logged": bool(mine),
            "model": None if latest is None else {
                "name": latest["model_version"], "p_home": latest["p_yes"],
                "created_ts": latest["created_ts"],
            },
        })  # fmt: skip
    return games


def build(
    root: Path,
    out: Path,
    forecasts_dir: Path | None = None,
    now: datetime | None = None,
    fees_fn=fetch_kalshi_fees,
) -> dict:
    now = now or datetime.now(UTC)
    forecasts_dir = forecasts_dir or root / "forecasts"
    kickoffs = json.loads((root / "config" / "kickoffs.json").read_text())
    kickoffs = [
        {"game_id": k["game_id"], "away": k["away"], "home": k["home"],
         "kickoff_utc": k["kickoff_utc"]}
        for k in kickoffs
    ]  # fmt: skip

    files, rows, problems = read_forecasts(root, forecasts_dir)
    games = build_games(kickoffs, files, rows)
    fees = fees_fn()
    stamps, quotes = build_market(root, games, kalshi_taker_rate(fees))
    if fees is None or kalshi_taker_rate(fees) is None:
        problems.append("Kalshi fee data unavailable: cross-venue gaps show gross cents only")
    if fees is not None:
        fees = {**fees, "taker_rate": kalshi_taker_rate(fees), "fetched_utc": iso(now)}
    if not ref_exists(root, MAIN_REF):
        problems.append(f"{MAIN_REF} not found: no forecast can count as pushed")

    head = git_text(root, "rev-parse", "HEAD")
    dref = data_ref(root)
    meta = {
        "built_utc": iso(now), "repo_url": REPO_URL, "commit": head,
        "commit_url": f"{REPO_URL}/commit/{head}",
        "data_commit": git_text(root, "rev-parse", dref) if dref else None,
        "snapshots": stamps,
        "games_total": len(games),
        "games_logged": sum(g["logged"] for g in games),
        "forecast_files": len(files),
        "problems": problems,
    }  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    payloads = {
        "meta.json": meta,
        "games.json": games,
        "market.json": {"snapshots": stamps, "fees": {"kalshi": fees}, "games": quotes},
        "forecasts.json": {"files": files, "rows": rows},
    }
    for name, payload in payloads.items():
        (out / name).write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n")
    for p in problems:
        print(f"warning: {p}", file=sys.stderr)
    print(
        f"site data: {len(games)} games, {meta['games_logged']} logged, "
        f"{len(quotes)} with prices, snapshots {stamps or 'none'} -> {out}"
    )
    return meta


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "site" / "data")
    ap.add_argument("--forecasts", type=Path, default=ROOT / "forecasts")
    ap.add_argument("--now", help="ISO time to stamp as the build time (tests)")
    args = ap.parse_args(argv)
    build(ROOT, args.out, args.forecasts, parse_ts(args.now) if args.now else None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
