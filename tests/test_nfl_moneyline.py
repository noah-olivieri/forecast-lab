"""Synthetic contracts for the evaluator-only historical moneyline reference."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from lab.backtest import nfl_moneyline as moneyline


def test_american_odds_and_both_devig_methods_have_hand_checkable_values():
    assert moneyline.american_implied_probability("+150") == pytest.approx(0.4)
    assert moneyline.american_implied_probability("-150") == pytest.approx(0.6)
    assert moneyline.american_implied_probability("0") is None

    proportional = moneyline.devig_pair("+100", "+100", method="proportional")
    assert proportional["status"] == "ok"
    assert proportional["p_home"] == pytest.approx(0.5)
    assert proportional["p_away"] == pytest.approx(0.5)

    power = moneyline.devig_pair("+100", "+100", method="power")
    assert power["status"] == "ok"
    assert power["k"] == pytest.approx(1.0)
    assert power["p_home"] == pytest.approx(0.5)


def test_pair_validation_distinguishes_missing_partial_and_invalid_quotes():
    assert moneyline.devig_pair("", "") ["status"] == "missing_pair"
    assert moneyline.devig_pair("+100", "") ["status"] == "partial_pair"
    assert moneyline.devig_pair("EVEN", "-110") ["status"] == "invalid_pair"
    with pytest.raises(ValueError, match="method"):
        moneyline.devig_pair("+100", "-110", method="best-line")


def test_power_method_solves_nontrivial_root_and_handles_invalid_numeric_prices():
    result = moneyline.devig_pair("+100", "-110", method="power")
    assert result["status"] == "ok"
    assert result["q_home"] ** result["k"] + result["q_away"] ** result["k"] == pytest.approx(1.0)
    assert result["p_home"] + result["p_away"] == pytest.approx(1.0)
    assert result["k"] != pytest.approx(1.0)
    assert moneyline.devig_pair("-1e309", "+100", method="power")["status"] == "invalid_pair"


def test_season_extraction_uses_season_key_and_refuses_overwrite(tmp_path):
    source = tmp_path / "unordered.csv"
    rows = [
        {"game_id": "holdout-secret", "season": "2024", "home_moneyline": "NOT-ODDS", "away_moneyline": "?"},
        {"game_id": "outer-2015", "season": "2015", "home_moneyline": "+100", "away_moneyline": "-110"},
    ]
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    output = tmp_path / "odds-v1"
    manifest = moneyline.extract_odds_partitions(source, output, source_commit="synthetic-fixture")
    assert manifest["development_seasons"] == list(range(2006, 2024))
    assert "holdout-secret" not in (output / "manifest.json").read_text()
    partition = next(part for part in manifest["partitions"] if part["season"] == 2015)
    partition_path = output / partition["path"]
    assert hashlib.sha256(partition_path.read_bytes()).hexdigest() == partition["sha256"]
    assert "outer-2015" in partition_path.read_text()
    assert moneyline.load_odds_partitions(output / "manifest.json")["outer-2015"]["season"] == 2015

    before = partition_path.read_bytes()
    with pytest.raises(FileExistsError):
        moneyline.extract_odds_partitions(source, output, source_commit="synthetic-fixture")
    assert partition_path.read_bytes() == before


def test_extractor_rejects_duplicate_game_ids_instead_of_emitting_ambiguous_odds(tmp_path):
    source = tmp_path / "duplicate.csv"
    with source.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["game_id", "season", "home_moneyline", "away_moneyline"])
        writer.writerow(["same-game", 2015, "+100", "-110"])
        writer.writerow(["same-game", 2015, "-110", "+100"])
    with pytest.raises(ValueError, match="duplicate game_id"):
        moneyline.extract_odds_partitions(source, tmp_path / "duplicate-output", source_commit="fixture")


def test_odds_manifest_sidecar_and_partition_hashes_are_verified(tmp_path):
    manifest_path = _write_odds_manifest(
        tmp_path / "hashed",
        [{"game_id": "game-1", "season": 2015, "home_moneyline": "+100", "away_moneyline": "-110"}],
    )
    sidecar = manifest_path.with_name("manifest.sha256")
    sidecar.write_text("0" * 64 + "\n")
    with pytest.raises(ValueError, match="manifest hash"):
        moneyline.load_odds_partitions(manifest_path)


def test_binary_scores_use_the_same_binary_target_and_clip_log_loss():
    score = moneyline.binary_score(0.8, 1)
    assert score["brier"] == pytest.approx(0.04)
    assert score["log_loss"] == pytest.approx(-math.log(0.8))
    assert score["clipped"] == 0

    extreme = moneyline.binary_score(1.0, 0)
    assert extreme["brier"] == 1.0
    assert extreme["clipped"] == 1
    assert extreme["unclipped_p"] == 1.0
    assert extreme["log_loss"] == pytest.approx(-math.log(1e-6))
    with pytest.raises(ValueError, match="decisive"):
        moneyline.binary_score(0.4, 0.5)


def test_rf001_conditional_probability_uses_only_home_and_away_mass():
    assert moneyline.conditional_home_probability(0.60, 0.36) == pytest.approx(0.625)
    assert moneyline.conditional_home_probability(0.0, 0.0) is None
    assert moneyline.conditional_home_probability(0.8, 0.8) is None
    assert moneyline.conditional_home_probability(float("nan"), 0.2) is None


def _write_odds_manifest(root: Path, odds_rows):
    root.mkdir(parents=True, exist_ok=True)
    source = root / "games.csv"
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("game_id", "season", "home_moneyline", "away_moneyline")
        )
        writer.writeheader()
        writer.writerows(odds_rows)
    output = root / "odds"
    moneyline.extract_odds_partitions(source, output, source_commit="synthetic-fixture")
    return output / "manifest.json"


def _saved_distribution(run_dir: Path, game_id: str):
    from lab.backtest.score_artifacts import RecordStore
    from lab.models.nfl_score import sample_scores

    as_of = "2015-09-02T16:00:00.000000Z"
    residuals = [[10, 0]] * 15 + [[0, 10]] * 9 + [[6.25, 3.75]]
    bank = [
        {
            "game_id": f"prior-{index:02d}",
            "kickoff": f"2015-07-{index + 1:02d}T16:00:00Z",
            "residual": residual,
        }
        for index, residual in enumerate(residuals)
    ]
    store = RecordStore(run_dir)
    bank_path = store.bank(bank)
    dist = sample_scores((20, 20), bank, game_id, as_of, 20261008, "REG", n_draws=10000)
    path = run_dir / f"{game_id}-{hashlib.sha256(game_id.encode()).hexdigest()[:6]}.npz"
    with path.open("wb") as handle:
        np.savez_compressed(handle, samples=dist.samples)
    return {
        **dist.summary,
        "seed": dist.seed,
        "samples_path": path.name,
        "samples_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bank_path": bank_path,
        "game_id": game_id,
        "as_of": as_of,
        "game_type": "REG",
        "fitted_home_mean": 20.0,
        "fitted_away_mean": 20.0,
    }


def _make_saved_run(root: Path, *, duplicate=False, holdout=False):
    root.mkdir()
    games = [
        ("home-win", "+100", "+100", 1),
        ("tie", "-110", "-110", 0.5),
        ("away-win", "-110", "+100", 0),
        ("no-rf-prediction", "+100", "+100", 1),
    ]
    odds_path = _write_odds_manifest(
        root / "odds-input",
        [
            {"game_id": gid, "season": 2015, "home_moneyline": home, "away_moneyline": away}
            for gid, home, away, _ in games
        ],
    )
    predictions, evaluation = [], []
    for gid, _home, _away, y in games:
        for model in ("rf001", "league", "elo", "home_rate", "half"):
            status = "miss" if gid == "no-rf-prediction" and model == "rf001" else "forecast"
            if model == "rf001" and gid == "away-win":
                status = "fallback"
            p = {"elo": 0.8, "home_rate": 1.0 if y == 0 else 0.7, "half": 0.5}.get(model)
            row = {
                "game_id": gid,
                "season": 2015,
                "week": 1 if gid != "away-win" else 2,
                "game_type": "REG",
                "kickoff": "2015-09-03T16:00:00.000000Z",
                "as_of": "2015-09-02T16:00:00.000000Z",
                "model": model,
                "role": "outer",
                "status": status,
                "p_share": p,
                "actual_model": "league-score-v1" if model == "rf001" and status == "fallback" else model,
            }
            if model in ("rf001", "league") and status != "miss":
                distribution = _saved_distribution(root, f"{gid}-{model}")
                row.update({k: v for k, v in distribution.items() if k not in ("game_id", "as_of", "game_type")})
            if duplicate and gid == "home-win" and model == "elo":
                predictions.append(dict(row))
            predictions.append(row)
            if status in ("forecast", "fallback"):
                home_score, away_score = (24, 17) if y == 1 else (17, 24) if y == 0 else (17, 17)
                evaluation.append(
                    {
                        **row,
                        "y": y,
                        "evaluation_label": {
                            "home_score": home_score,
                            "away_score": away_score,
                            "completed": True,
                        },
                    }
                )

    predictions_bytes = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in reversed(predictions)
    )
    evaluation_path = root / "evaluation.json"
    evaluation_path.write_text(json.dumps(list(reversed(evaluation))))
    (root / "predictions.jsonl").write_bytes(predictions_bytes)
    metrics = {
        "outer": {"rf001": {"attempted": 4, "eligible": 4, "excluded": 0}},
        "comparisons": {
            name: {"common_game_ids": ["home-win", "tie", "away-win"]}
            for name in ("league", "elo", "home_rate", "half")
        },
    }
    (root / "metrics.json").write_text(json.dumps(metrics))
    source_manifest = {
        "synthetic": True,
        "cohort": "reconstructed_scores",
        "partitions": [{"season": season} for season in range(2006, 2024)],
    }
    if holdout:
        source_manifest["partitions"].append({"season": 2024})
        evaluation_path.write_text("not-json-holdout-outcomes")
    run_manifest = {
        "status": "complete",
        "config": {"run_seed": 20261008, "final_holdout_access": False},
        "provenance": {"alias_version": "franchise-v1", "uv_lock_hash": "synthetic-lock"},
        "source_manifest": source_manifest,
        "predictions_hash": hashlib.sha256(predictions_bytes).hexdigest(),
    }
    (root / "manifest.json").write_text(json.dumps(run_manifest))
    return odds_path, root, predictions_bytes


def test_evaluator_excludes_ties_pairs_by_game_id_and_keeps_fallbacks(tmp_path):
    odds_path, run_dir, prediction_bytes = _make_saved_run(tmp_path / "run")
    report = moneyline.evaluate_saved_run(run_dir, odds_path)

    assert report["label"] == moneyline.REFERENCE_LABEL
    assert report["coverage"]["valid_moneyline_pairs"] == 4
    assert report["coverage"]["ties_excluded"] == 1
    assert report["models"]["rf001"]["n"] == 2
    assert report["models"]["rf001"]["fallback_predictions"] == 1
    assert report["models"]["rf001"]["missing_predictions"] == 1
    assert report["models"]["rf001"]["game_ids"] == ["away-win", "home-win"]
    saved = [
        row
        for row in json.loads((run_dir / "evaluation.json").read_text())
        if row["model"] == "rf001" and row["game_id"] in {"home-win", "away-win"}
    ]
    hand_probabilities = [row["p_home"] / (row["p_home"] + row["p_away"]) for row in saved]
    hand_outcomes = [row["y"] for row in saved]
    expected_brier = sum((p - y) ** 2 for p, y in zip(hand_probabilities, hand_outcomes, strict=True)) / 2
    assert report["models"]["rf001"]["brier"] == pytest.approx(expected_brier)
    assert report["models"]["rf001"]["model_mean_probability"] == pytest.approx(0.625, abs=0.01)
    assert report["registered_football_pairwise_populations"]["elo"] == [
        "home-win",
        "tie",
        "away-win",
    ]
    assert report["all_model_complete_case_descriptive"]["n"] == 2
    assert report["models"]["rf001"]["by_season"]["2015"]["n"] == 2
    assert report["pairwise_market_comparisons"]["rf001"]["brier"]["n"] == 2
    assert report["pairwise_market_comparisons"]["rf001"]["log_loss"]["n"] == 2
    assert report["provenance"]["runner_provenance"]["alias_version"] == "franchise-v1"
    assert (run_dir / "predictions.jsonl").read_bytes() == prediction_bytes


def test_evaluator_rejects_duplicate_predictions_and_holdout_before_reading_labels(tmp_path):
    odds_path, duplicate_run, _ = _make_saved_run(tmp_path / "duplicate", duplicate=True)
    with pytest.raises(ValueError, match="duplicate.*prediction"):
        moneyline.evaluate_saved_run(duplicate_run, odds_path)

    odds_path, holdout_run, _ = _make_saved_run(tmp_path / "holdout", holdout=True)
    with pytest.raises(ValueError, match="holdout"):
        moneyline.evaluate_saved_run(holdout_run, odds_path)


def test_odds_changes_cannot_mutate_saved_predictions_or_model_probabilities(tmp_path):
    odds_path, run_dir, prediction_bytes = _make_saved_run(tmp_path / "run")
    original = moneyline.evaluate_saved_run(run_dir, odds_path)
    changed_odds = _write_odds_manifest(
        tmp_path / "changed-input",
        [
            {"game_id": "home-win", "season": 2015, "home_moneyline": "-200", "away_moneyline": "+150"},
            {"game_id": "away-win", "season": 2015, "home_moneyline": "+150", "away_moneyline": "-200"},
        ],
    )
    changed = moneyline.evaluate_saved_run(run_dir, changed_odds)
    assert changed["models"]["rf001"]["model_mean_probability"] == original["models"]["rf001"]["model_mean_probability"]
    assert changed["market"]["p_home_mean"] != original["market"]["p_home_mean"]
    assert (run_dir / "predictions.jsonl").read_bytes() == prediction_bytes


def test_pairwise_log_loss_reports_clipping_and_power_sensitivity(tmp_path):
    odds_path, run_dir, _ = _make_saved_run(tmp_path / "run")
    report = moneyline.evaluate_saved_run(run_dir, odds_path)
    home_rate = report["models"]["home_rate"]
    assert home_rate["clipped_log_losses"] == 1
    expected_log_loss = (-math.log(0.7) - math.log(1e-6) - math.log(0.7)) / 3
    assert home_rate["log_loss"] == pytest.approx(expected_log_loss)
    assert report["market"]["power_sensitivity"]["n"] == report["market"]["n"]
    assert report["models"]["rf001"]["monte_carlo_sensitivity"]["status"] == "scored"
    assert report["models"]["rf001"]["monte_carlo_sensitivity"]["draws"] == 20000


def test_scalar_reports_disclose_the_conditional_probability_approximation(tmp_path):
    odds_path, run_dir, _ = _make_saved_run(tmp_path / "run")
    report = moneyline.evaluate_saved_run(run_dir, odds_path)
    for model in ("elo", "home_rate"):
        disclosure = report["models"][model]["probability_interpretation"]
        assert "unadjusted" in disclosure
        assert "approximation" in disclosure
        assert "conditional decisive-game" in disclosure
        assert "no separately identified tie probability" in disclosure


@pytest.mark.parametrize(
    ("home_count", "difference", "threshold", "flagged"),
    [(7500, 0.25, 0.01399038105676658, True), (10000, 0.0, 0.001, False)],
)
def test_conditional_mc_uses_independent_seed_and_hand_checked_threshold(
    tmp_path, home_count, difference, threshold, flagged
):
    from lab.backtest.score_artifacts import RecordStore

    game_id, as_of = "invented-game", "2015-09-02T16:00:00.000000Z"
    # Derive seeds from the documented SHA-256 contract, independently of
    # stable_seed. sample_scores hashes the alternate run seed once more.
    def seed_from_text(value):
        return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")

    primary_seed = seed_from_text(f"20261008|{game_id}|{as_of}|distribution-v1")
    alternate = seed_from_text(f"20261008|{game_id}|{as_of}|mc-sensitivity-v1")
    expected_repeat_seed = seed_from_text(f"{alternate}|{game_id}|{as_of}|distribution-v1")
    bank_path = RecordStore(tmp_path).bank(
        [{"game_id": "prior", "kickoff": "2015-08-01T16:00:00Z", "residual": [0, 0]}]
    )
    # Repeat draws are deterministically all home wins. The saved primary draws
    # deliberately differ to exercise the diagnostic's flagged branch.
    samples = np.array([[21, 20]] * home_count + [[20, 21]] * (10000 - home_count))
    path = tmp_path / "primary.npz"
    np.savez_compressed(path, samples=samples)
    prediction = {
        "samples_path": path.name,
        "samples_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bank_path": bank_path,
        "p_home": home_count / 10000,
        "p_away": (10000 - home_count) / 10000,
        "p_tie": 0.0,
        "fitted_home_mean": 21.0,
        "fitted_away_mean": 20.0,
        "seed": primary_seed,
    }
    result = moneyline._read_distribution(
        tmp_path,
        prediction,
        {"game_id": game_id, "as_of": as_of, "run_seed": 20261008, "game_type": "REG"},
    )
    assert result["seed"] == expected_repeat_seed
    assert result["seed"] != prediction["seed"]
    assert result["base_decisive_draws"] == 10000
    assert result["repeat_decisive_draws"] == 20000
    assert result["repeat_p_cond"] == 1.0
    assert result["difference"] == pytest.approx(difference)
    # For .75 versus 1: 3*sqrt(.75*.25/10000 + 1*0/20000)+.001.
    assert result["threshold"] == pytest.approx(threshold)
    assert result["flagged"] is flagged
