"""QB-001: frozen Elo plus a backup-QB flag, as pre-registered in research/QB001_PREREG.md.

    PYTHON_DOTENV_DISABLED=1 uv run python -m lab.backtest.qb_flag \
        --manifest data/research/inputs/.../execution-manifest.json \
        --odds-manifest data/research/odds/.../manifest.json \
        --starters data/research/sources/.../games.csv --run-id qb001-backup-flag-v1

Frozen Elo is called unchanged; the flag only shifts that game's probability. Rating
updates never see the penalty. Odds are evaluator-only and never reach a prediction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np

from lab.backtest.nfl_moneyline import (
    SOURCE_SHA256,
    binary_score,
    load_odds_partitions,
)
from lab.backtest.nfl_score import frozen_predictions
from lab.backtest.score_data import (
    ALIASES,
    FINISH_LAG,
    canonical,
    digest,
    load_manifest,
    stamp,
    validate_execution_policy,
    validate_population,
)
from lab.eval.score_metrics import paired_bootstrap, probability_losses
from lab.models import nfl_elo

ROOT = Path(__file__).resolve().parents[3]
PENALTIES = tuple(range(9))  # points of spread
ELO_PER_POINT = 25.0
WINDOW = 8
TUNE_SEASONS = range(2006, 2015)
TEST_SEASONS = range(2015, 2024)
PROVENANCE_PATHS = (
    "src/lab/backtest/qb_flag.py",
    "src/lab/backtest/nfl_score.py",
    "src/lab/backtest/nfl_moneyline.py",
    "src/lab/backtest/score_data.py",
    "src/lab/eval/score_metrics.py",
    "src/lab/features/nfl.py",
    "src/lab/models/nfl_elo.py",
    "research/QB001_PREREG.md",
    "uv.lock",
)


def load_starters(path, expected_sha256=SOURCE_SHA256):
    """{game_id: teams and starter IDs} for 2006-2023 from the pinned games.csv."""
    content = Path(path).read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("starter source hash mismatch")
    starters = {}
    for row in csv.DictReader(content.decode("utf-8").splitlines()):
        if not 2006 <= int(row["season"]) <= 2023:
            continue  # 2024-2025 stay locked; pre-2006 is outside the prepared data
        if row["game_id"] in starters:
            raise ValueError("duplicate game_id in starter source")
        starters[row["game_id"]] = {
            "home_team": ALIASES.get(row["home_team"], row["home_team"]),
            "away_team": ALIASES.get(row["away_team"], row["away_team"]),
            "home_qb": _qb(row["home_qb_id"]),
            "away_qb": _qb(row["away_qb_id"]),
        }
    return starters


def _qb(value):
    value = (value or "").strip()
    return None if value in ("", "NA") else value


def usual_starter(starts):
    """Most starts in the last 8 games with a known starter; ties go to the most recent."""
    window = [qb for qb in starts if qb is not None][-WINDOW:]
    if not window:
        return None
    counts = Counter(window)
    best = max(counts.values())
    last_start = {qb: i for i, qb in enumerate(window)}
    return max((qb for qb, n in counts.items() if n == best), key=last_start.__getitem__)


def backup_flags(game, prior, starters):
    """Flag each team whose starter tonight is not its usual starter."""
    if any(
        o.game.game_id == game.game_id or o.game.kickoff + FINISH_LAG >= game.as_of for o in prior
    ):
        raise ValueError("target or later game in QB history")
    tonight = starters.get(game.game_id, {})
    ordered = sorted(prior, key=lambda o: (o.game.kickoff, o.game.game_id))
    result = {}
    for side, team in (("home", game.home_team), ("away", game.away_team)):
        starts = []
        for o in ordered:
            if team not in (o.game.home_team, o.game.away_team):
                continue
            was = "home" if o.game.home_team == team else "away"
            starts.append(starters.get(o.game.game_id, {}).get(f"{was}_qb"))
        usual, qb = usual_starter(starts), tonight.get(f"{side}_qb")
        result.update(
            {
                side: usual is not None and qb is not None and qb != usual,
                f"{side}_usual": usual,
                f"{side}_tonight": qb,
            }
        )
    return result


def adjusted_probability(p, home_penalty, away_penalty):
    """Frozen Elo P(home) after subtracting Elo penalties from each team's rating.

    Frozen Elo is logistic in the rating gap, so the gap is recovered from p and shifted.
    """
    if home_penalty == 0 and away_penalty == 0:
        return p
    gap = nfl_elo.SCALE * math.log10(p / (1 - p))
    return nfl_elo.expected_home(gap - home_penalty, -away_penalty, hfa=0.0)


def choose_penalty(brier_by_penalty):
    """Lowest Brier; ties go to the smaller penalty."""
    best = None
    for points in sorted(brier_by_penalty):
        if best is None or brier_by_penalty[points] < brier_by_penalty[best]:
            best = points
    return best


def score_games(dataset, starters):
    """One row per target game: frozen Elo, flags and P(home) at every grid penalty."""
    rows = []
    for game in dataset.targets():
        known = starters.get(game.game_id)
        if known and (known["home_team"], known["away_team"]) != (game.home_team, game.away_team):
            raise ValueError(f"starter source teams disagree: {game.game_id}")
        prior = dataset.eligible(game.as_of)
        p_elo = frozen_predictions(prior, game)["elo"]
        flags = backup_flags(game, prior, starters)
        label = dataset.evaluation_label(game.game_id)
        y = None
        if label is not None:
            margin = label.home_score - label.away_score
            y = 1 if margin > 0 else 0 if margin < 0 else 0.5
        p = [
            adjusted_probability(
                p_elo,
                points * ELO_PER_POINT if flags["home"] else 0.0,
                points * ELO_PER_POINT if flags["away"] else 0.0,
            )
            for points in PENALTIES
        ]
        rows.append(
            {
                "game_id": game.game_id,
                "season": game.season,
                "week": game.week,
                "game_type": game.game_type,
                "kickoff": stamp(game.kickoff),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "home_flag": flags["home"],
                "away_flag": flags["away"],
                "home_usual": flags["home_usual"],
                "home_tonight": flags["home_tonight"],
                "away_usual": flags["away_usual"],
                "away_tonight": flags["away_tonight"],
                "p_elo": p_elo,
                "p": p,
                "y": y,
            }
        )
    return rows


def _mean(values):
    return float(np.mean(values)) if values else None


def _paired(rows, loss_a, loss_b):
    """Registered paired block bootstrap of loss_a - loss_b, per metric."""
    result = {}
    for metric in ("brier", "log_loss"):
        diffs = [
            {
                **{k: r[k] for k in ("game_id", "season", "week", "game_type", "kickoff")},
                "difference": loss_a(r)[metric] - loss_b(r)[metric],
            }
            for r in rows
        ]
        value = paired_bootstrap(diffs)
        value["per_season"] = {
            str(s): _mean([d["difference"] for d in diffs if d["season"] == s])
            for s in sorted({d["season"] for d in diffs})
        }
        result[metric] = value
    return result


def _summary(rows, k):
    def losses(p):
        return [probability_losses(p(r), r["y"]) for r in rows]

    elo, flag = losses(lambda r: r["p_elo"]), losses(lambda r: r["p"][k])
    return {
        "n": len(rows),
        "games_flagged": sum(r["home_flag"] or r["away_flag"] for r in rows),
        "flag_rate_games": _mean([float(r["home_flag"] or r["away_flag"]) for r in rows]),
        "flag_rate_teams": _mean([(r["home_flag"] + r["away_flag"]) / 2 for r in rows]),
        "elo_brier": _mean([x["brier"] for x in elo]),
        "flag_brier": _mean([x["brier"] for x in flag]),
        "elo_log_loss": _mean([x["log_loss"] for x in elo]),
        "flag_log_loss": _mean([x["log_loss"] for x in flag]),
        "brier_difference": _mean(
            [b["brier"] - a["brier"] for a, b in zip(elo, flag, strict=True)]
        ),
    }


def report(rows, odds):
    scored = [r for r in rows if r["y"] is not None]
    tune = [r for r in scored if r["season"] in TUNE_SEASONS]
    test = [r for r in scored if r["season"] in TEST_SEASONS]
    grid = {
        points: _mean([probability_losses(r["p"][i], r["y"])["brier"] for r in tune])
        for i, points in enumerate(PENALTIES)
    }
    chosen = choose_penalty(grid)
    k = PENALTIES.index(chosen)

    def flag_loss(r):
        return probability_losses(r["p"][k], r["y"])

    def elo_loss(r):
        return probability_losses(r["p_elo"], r["y"])

    all_games = _paired(test, flag_loss, elo_loss)
    decisive = [
        r
        for r in test
        if r["y"] in (0, 1)
        and odds.get(r["game_id"], {}).get("proportional", {}).get("status") == "ok"
    ]

    def ml_loss(r):
        return binary_score(odds[r["game_id"]]["proportional"]["p_home"], r["y"])

    def flag_binary(r):
        return binary_score(r["p"][k], r["y"])

    def elo_binary(r):
        return binary_score(r["p_elo"], r["y"])

    ci = all_games["brier"]["ci95"]
    return {
        "prereg": "research/QB001_PREREG.md",
        "penalty_grid_points": list(PENALTIES),
        "elo_per_point": ELO_PER_POINT,
        "tune_brier_by_penalty": {str(p): v for p, v in grid.items()},
        "tune_n": len(tune),
        "chosen_penalty_points": chosen,
        "chosen_penalty_elo": chosen * ELO_PER_POINT,
        "success": bool(ci and ci[1] < 0),
        "tune": _summary(tune, k),
        "test": _summary(test, k),
        "test_all_games_flag_minus_elo": all_games,
        "decisive_moneyline": {
            "label": "historical moneyline reference; timing and book unknown",
            "n": len(decisive),
            "elo_brier": _mean([elo_binary(r)["brier"] for r in decisive]),
            "flag_brier": _mean([flag_binary(r)["brier"] for r in decisive]),
            "moneyline_brier": _mean([ml_loss(r)["brier"] for r in decisive]),
            "elo_log_loss": _mean([elo_binary(r)["log_loss"] for r in decisive]),
            "flag_log_loss": _mean([flag_binary(r)["log_loss"] for r in decisive]),
            "moneyline_log_loss": _mean([ml_loss(r)["log_loss"] for r in decisive]),
            "flag_minus_elo": _paired(decisive, flag_binary, elo_binary),
            "flag_minus_moneyline": _paired(decisive, flag_binary, ml_loss),
            "elo_minus_moneyline": _paired(decisive, elo_binary, ml_loss),
        },
        "per_season": {
            str(s): _summary([r for r in scored if r["season"] == s], k)
            for s in sorted({r["season"] for r in scored})
        },
        "test_weeks_1_4": _summary(
            [r for r in test if r["game_type"] == "REG" and r["week"] <= 4], k
        ),
        "test_after_week_4": _summary(
            [r for r in test if not (r["game_type"] == "REG" and r["week"] <= 4)], k
        ),
        "test_flagged_games_descriptive": _summary(
            [r for r in test if r["home_flag"] or r["away_flag"]], k
        ),
        "test_missing_tonight_ids": sum(
            r["home_tonight"] is None or r["away_tonight"] is None for r in test
        ),
        "test_no_usual_starter": sum(
            r["home_usual"] is None or r["away_usual"] is None for r in test
        ),
    }


def provenance():
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PROVENANCE_PATHS}
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    patch = subprocess.check_output(["git", "diff", "HEAD", "--", *PROVENANCE_PATHS], cwd=ROOT)
    return {
        "git_sha": sha,
        "dirty_patch_hash": hashlib.sha256(patch).hexdigest(),
        "provenance_dirty": bool(patch),
        "working_file_hashes": hashes,
    }


def run(manifest_path, odds_manifest_path, starters_path, output_root=None, run_id=None):
    dataset, source_manifest = load_manifest(Path(manifest_path), require_execution_policy=True)
    if source_manifest["synthetic"]:
        raise ValueError("QB-001 runs only on the reviewed real manifest")
    validate_execution_policy(source_manifest, required=True)
    if not all(
        p.get("audit", {}).get("kickoff_and_label_coverage_reviewed")
        for p in source_manifest["partitions"]
    ):
        raise ValueError("real run requires kickoff/label coverage audit")
    validate_population(dataset, source_manifest)
    out = Path(output_root or ROOT / "data/research/runs").resolve() / run_id
    if "forecasts" in out.parts:
        raise ValueError("research outputs cannot enter forecasts")
    out.mkdir(parents=True, exist_ok=False)

    def write(name, value):
        with (out / name).open("x") as handle:
            handle.write(canonical(value) + "\n")

    inputs = {
        str(p): hashlib.sha256(Path(p).read_bytes()).hexdigest()
        for p in (manifest_path, odds_manifest_path, starters_path)
    }
    config = {
        "run_id": run_id,
        "penalties": list(PENALTIES),
        "elo_per_point": ELO_PER_POINT,
        "window": WINDOW,
        "tune_seasons": [TUNE_SEASONS.start, TUNE_SEASONS.stop - 1],
        "test_seasons": [TEST_SEASONS.start, TEST_SEASONS.stop - 1],
        "final_holdout_access": False,
        "inputs_sha256": inputs,
    }
    write("started.json", {"config": config, "provenance": provenance(), "status": "running"})
    starters = load_starters(starters_path)
    rows = score_games(dataset, starters)
    with (out / "games.jsonl").open("x") as handle:
        for row in rows:
            handle.write(canonical(row) + "\n")
    metrics = report(rows, load_odds_partitions(odds_manifest_path))
    write("metrics.json", metrics)
    write(
        "manifest.json",
        {
            "config": config,
            "provenance": provenance(),
            "status": "complete",
            "games_sha256": hashlib.sha256((out / "games.jsonl").read_bytes()).hexdigest(),
            "metrics_digest": digest(metrics),
        },
    )
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--odds-manifest", type=Path, required=True)
    parser.add_argument("--starters", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        out = run(args.manifest, args.odds_manifest, args.starters, run_id=args.run_id)
    except (ValueError, FileExistsError) as exc:
        parser.exit(2, f"QB-001 refused: {exc}\n")
    print(out)


if __name__ == "__main__":
    main()
