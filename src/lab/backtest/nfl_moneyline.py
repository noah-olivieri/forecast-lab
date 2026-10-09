"""Local, evaluator-only historical NFL moneyline reference.

This module never invokes the RF-001 runner and never supplies odds to model
training or prediction code. The source's timing, book, aggregation, and
settlement semantics are not established; normalized two-way odds are treated
as conditional decisive-game probabilities only as an explicit research
assumption.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import Path

import numpy as np

from lab.backtest.score_artifacts import read_bank
from lab.eval.score_metrics import probability_losses
from lab.models.nfl_score import DistributionUnavailable, sample_scores, stable_seed

DEVELOPMENT_SEASONS = tuple(range(2006, 2024))
OUTER_SEASONS = tuple(range(2015, 2024))
SOURCE_COMMIT = "93a5221070bcd1733fe3c55abb48e931b3615241"
SOURCE_SHA256 = "fb2a5a96e2bd0ddc1b6ddbd487c89857b216114e5ce296214e5b54b6d75bbc43"
REFERENCE_LABEL = "historical moneyline reference; timing and book unknown"
SCHEMA = "rf001-moneyline-odds-v1"


def _is_missing(value):
    return value is None or (isinstance(value, str) and not value.strip())


def american_implied_probability(value):
    """Convert a finite integer American price with abs(price) >= 100 to q."""
    if isinstance(value, bool) or _is_missing(value):
        return None
    try:
        odds = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not odds.is_finite() or odds != odds.to_integral_value() or abs(odds) < 100:
        return None
    number = float(odds)
    if not math.isfinite(number):
        return None
    if odds > 0:
        return 100.0 / (number + 100.0)
    if odds < 0:
        magnitude = -number
        return magnitude / (magnitude + 100.0)
    return None


def devig_pair(home_odds, away_odds, *, method="proportional"):
    """Return normalized two-way probabilities and visible unsupported status."""
    if method not in {"proportional", "power"}:
        raise ValueError("method must be proportional or power")
    home_missing, away_missing = _is_missing(home_odds), _is_missing(away_odds)
    if home_missing and away_missing:
        return {"status": "missing_pair", "method": method}
    if home_missing or away_missing:
        return {"status": "partial_pair", "method": method}
    q_home = american_implied_probability(home_odds)
    q_away = american_implied_probability(away_odds)
    if q_home is None or q_away is None:
        return {"status": "invalid_pair", "method": method}
    if not (0 < q_home < 1 and 0 < q_away < 1):
        return {"status": "invalid_pair", "method": method}

    result = {"status": "ok", "method": method, "q_home": q_home, "q_away": q_away}
    if method == "proportional":
        denominator = q_home + q_away
        if not math.isfinite(denominator) or denominator <= 0:
            return {"status": "unsupported_proportional", "method": method}
        result.update(p_home=q_home / denominator, p_away=q_away / denominator)
        return result

    # For q_i in (0, 1), the left side is strictly decreasing from 2 to 0,
    # giving one positive root. Bracket by doubling and solve by fixed bisection.
    def equation(k):
        return q_home**k + q_away**k

    low, high = 0.0, 1.0
    try:
        while equation(high) > 1.0:
            high *= 2.0
            if not math.isfinite(high):
                raise ArithmeticError
        for _ in range(100):
            middle = (low + high) / 2.0
            if equation(middle) > 1.0:
                low = middle
            else:
                high = middle
            if high - low <= 1e-12:
                break
        if high - low > 1e-12:
            raise ArithmeticError
        k = (low + high) / 2.0
        powered_home, powered_away = q_home**k, q_away**k
        total = powered_home + powered_away
        if not math.isfinite(total) or total <= 0:
            raise ArithmeticError
    except (ArithmeticError, OverflowError, ValueError):
        return {"status": "unsupported_power", "method": method, "reason": "root_failure"}
    result.update(k=k, p_home=powered_home / total, p_away=powered_away / total)
    return result


def conditional_home_probability(p_home, p_away):
    """Derive RF-001's conditional decisive-game probability; zero is unsupported."""
    try:
        home, away = float(p_home), float(p_away)
    except (TypeError, ValueError):
        return None
    denominator = home + away
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in (home, away)):
        return None
    if denominator > 1.0 + 1e-12:
        return None
    if not math.isfinite(denominator) or denominator <= 0:
        return None
    return home / denominator


def binary_score(probability, outcome):
    """Score a decisive 0/1 result with registered Brier and clipped log loss."""
    try:
        probability, outcome = float(probability), float(outcome)
    except (TypeError, ValueError) as exc:
        raise ValueError("finite decisive probability and outcome required") from exc
    if not math.isfinite(probability) or not 0 <= probability <= 1 or outcome not in (0.0, 1.0):
        raise ValueError("finite probability in [0,1] and decisive 0/1 outcome required")
    return probability_losses(probability, outcome)


def _sha256(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def extract_odds_partitions(source_path, output_dir, *, source_commit, expected_source_sha256=None):
    """Extract odds-only 2006–2023 season partitions, independent of file order.

    Only season, game_id, and the two moneyline fields are accessed after the
    header. All other source columns, including holdout outcomes, are ignored.
    """
    source_path, output_dir = Path(source_path), Path(output_dir)
    source_bytes = source_path.read_bytes()
    actual_source_hash = hashlib.sha256(source_bytes).hexdigest()
    if expected_source_sha256 and actual_source_hash != expected_source_sha256:
        raise ValueError("pinned source hash mismatch")
    if not isinstance(source_commit, str) or not source_commit:
        raise ValueError("source commit required")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(exist_ok=False)
    by_season = {year: [] for year in DEVELOPMENT_SEASONS}
    seen_ids = set()
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("pinned odds source must be UTF-8 CSV") from exc
    with StringIO(source_text, newline="") as handle:
        reader = csv.reader(handle)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise ValueError("empty source CSV") from exc
        required = {"season", "game_id", "home_moneyline", "away_moneyline"}
        if len(headers) != len(set(headers)) or not required.issubset(headers):
            raise ValueError(f"pinned odds source missing required columns: {sorted(required - set(headers))}")
        positions = {name: headers.index(name) for name in required}
        for line_number, row in enumerate(reader, start=2):
            if len(row) != len(headers):
                raise ValueError(f"malformed source row at line {line_number}")
            try:
                season = int(row[positions["season"]])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid season key at line {line_number}") from exc
            if season not in by_season:
                continue
            game_id = row[positions["game_id"]].strip()
            if not game_id:
                raise ValueError(f"missing game_id in development season at line {line_number}")
            if game_id in seen_ids:
                raise ValueError(f"duplicate game_id in pinned source: {game_id}")
            seen_ids.add(game_id)
            by_season[season].append(
                {
                    "game_id": game_id,
                    "season": season,
                    "home_moneyline": row[positions["home_moneyline"]],
                    "away_moneyline": row[positions["away_moneyline"]],
                }
            )

    partitions = []
    for season, rows in by_season.items():
        rows.sort(key=lambda item: item["game_id"])
        relative = f"season={season}.csv"
        destination = output_dir / relative
        with destination.open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("game_id", "season", "home_moneyline", "away_moneyline"),
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        partitions.append(
            {"season": season, "path": relative, "rows": len(rows), "sha256": _sha256(destination)}
        )

    manifest = {
        "schema": SCHEMA,
        "source": {
            "repository": "nflverse/nfldata",
            "commit": source_commit,
            "file": source_path.name,
            "sha256": actual_source_hash,
            "selected_columns": ["season", "game_id", "home_moneyline", "away_moneyline"],
        },
        "extraction": {
            "version": 1,
            "extractor_sha256": _sha256(Path(__file__)),
            "python": sys.version.split()[0],
            "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "season_filter": list(DEVELOPMENT_SEASONS),
            "row_order": "sorted by game_id within season",
        },
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "partitions": partitions,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_bytes(_json_bytes(manifest))
    (output_dir / "manifest.sha256").write_text(_sha256(manifest_path) + "\n")
    return manifest


def load_odds_partitions(manifest_path):
    """Verify manifest and each content-hashed season file before returning rows."""
    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("odds manifest must be a regular local file")
    sidecar = manifest_path.with_name("manifest.sha256")
    manifest_bytes = manifest_path.read_bytes()
    if sidecar.is_symlink() or not sidecar.is_file() or sidecar.read_text().strip() != hashlib.sha256(manifest_bytes).hexdigest():
        raise ValueError("odds manifest hash mismatch")
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != SCHEMA or manifest.get("development_seasons") != list(DEVELOPMENT_SEASONS):
        raise ValueError("unsupported odds manifest/seasons")
    partitions = manifest.get("partitions", [])
    if [part.get("season") for part in partitions] != list(DEVELOPMENT_SEASONS):
        raise ValueError("odds partitions must cover exactly 2006–2023")
    records = {}
    for part in partitions:
        relative = part.get("path", "")
        if relative != f"season={part['season']}.csv":
            raise ValueError("unsafe odds partition path")
        path = manifest_path.parent / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"odds partition hash mismatch: {relative}")
        partition_bytes = path.read_bytes()
        if hashlib.sha256(partition_bytes).hexdigest() != part.get("sha256"):
            raise ValueError(f"odds partition hash mismatch: {relative}")
        with StringIO(partition_bytes.decode("utf-8"), newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["game_id", "season", "home_moneyline", "away_moneyline"]:
                raise ValueError(f"invalid odds partition schema: {relative}")
            rows = list(reader)
        if len(rows) != part.get("rows"):
            raise ValueError(f"odds partition row count mismatch: {relative}")
        for row in rows:
            game_id = row["game_id"]
            if int(row["season"]) != part["season"] or game_id in records:
                raise ValueError("duplicate game ID or season mismatch in odds partitions")
            records[game_id] = {
                **row,
                "season": int(row["season"]),
                "proportional": devig_pair(row["home_moneyline"], row["away_moneyline"]),
                "power": devig_pair(row["home_moneyline"], row["away_moneyline"], method="power"),
            }
    return records


def _read_jsonl_bytes(content, filename):
    rows = []
    for line_number, line in enumerate(content.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL row {line_number}: {filename}") from exc
    return rows


def _model_seasons(manifest):
    source = manifest.get("source_manifest", {})
    seasons = set()
    for partition in source.get("partitions", []):
        values = partition.get("seasons", [partition.get("season")])
        for value in values:
            if value is not None:
                seasons.add(int(value))
    if not seasons or min(seasons) < min(DEVELOPMENT_SEASONS) or max(seasons) > max(DEVELOPMENT_SEASONS):
        raise ValueError("runner manifest includes unsupported or holdout seasons")
    config = manifest.get("config", {})
    for key in ("development_seasons", "outer_seasons"):
        value = config.get(key)
        if value and (len(value) != 2 or value[0] < 2006 or value[1] > 2023):
            raise ValueError("runner config includes holdout seasons")
    if config.get("final_holdout_access") is not False:
        raise ValueError("runner manifest does not prove the holdout is locked")
    return seasons


def _safe_run_file(run_dir, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe runner artifact path")
    candidate = Path(run_dir) / path
    result = candidate.resolve()
    if candidate.is_symlink() or Path(run_dir).resolve() not in result.parents or not result.is_file():
        raise ValueError("runner artifact is missing or unsafe")
    return result


def _outcome(row):
    label = row.get("evaluation_label")
    if not isinstance(label, dict) or type(label.get("home_score")) is not int or type(label.get("away_score")) is not int:
        raise ValueError("saved evaluation requires integer final scores")
    derived = 1.0 if label["home_score"] > label["away_score"] else 0.0 if label["home_score"] < label["away_score"] else 0.5
    if float(row.get("y")) != derived:
        raise ValueError("saved evaluation target disagrees with its final score")
    return derived


def _read_distribution(run_dir, prediction, evaluation):
    from lab.backtest.score_data import utc
    relative = prediction.get("samples_path")
    bank_ref = prediction.get("bank_path")
    if not relative or not bank_ref:
        return {"status": "unsupported", "reason": "saved_distribution_artifacts_missing"}
    samples_path = _safe_run_file(run_dir, relative)
    samples_bytes = samples_path.read_bytes()
    if hashlib.sha256(samples_bytes).hexdigest() != prediction.get("samples_hash"):
        raise ValueError("saved prediction sample hash mismatch")
    with np.load(BytesIO(samples_bytes), allow_pickle=False) as archive:
        samples = archive["samples"]
    if samples.ndim != 2 or samples.shape[1] != 2 or not len(samples) or not np.issubdtype(samples.dtype, np.integer):
        raise ValueError("saved score samples have invalid shape or dtype")
    if not np.isfinite(samples).all() or (samples < 0).any():
        raise ValueError("saved score samples are invalid")
    home, away = samples.T
    counts = {
        "p_home": float(np.mean(home > away)),
        "p_away": float(np.mean(home < away)),
        "p_tie": float(np.mean(home == away)),
    }
    for key, value in counts.items():
        if not math.isclose(float(prediction.get(key, math.nan)), value, abs_tol=1e-12):
            raise ValueError(f"saved probability disagrees with samples: {key}")
    probability = conditional_home_probability(prediction.get("p_home"), prediction.get("p_away"))
    if probability is None:
        return {"status": "unsupported", "reason": "zero_or_invalid_conditional_denominator"}
    decisive_count = int(np.count_nonzero(home != away))
    if decisive_count == 0:
        return {"status": "unsupported", "reason": "no_decisive_saved_samples"}

    try:
        bank = read_bank(run_dir, bank_ref)
        as_of = utc(evaluation["as_of"])
        seed = stable_seed(
            int(evaluation["run_seed"]), evaluation["game_id"], as_of, "mc-sensitivity-v1"
        )
        repeat = sample_scores(
            (float(prediction["fitted_home_mean"]), float(prediction["fitted_away_mean"])),
            bank,
            evaluation["game_id"],
            as_of,
            seed,
            evaluation["game_type"],
            n_draws=20000,
        )
    except DistributionUnavailable as exc:
        # Failed secondary sampling does not invalidate the saved primary forecast.
        return {
            "status": "unsupported",
            "reason": f"sensitivity_sampling_failed:{type(exc).__name__}",
            "p_cond": probability,
        }
    p_repeat = conditional_home_probability(repeat.summary["p_home"], repeat.summary["p_away"])
    repeat_decisive = 20000 * (repeat.summary["p_home"] + repeat.summary["p_away"])
    if p_repeat is None or repeat_decisive <= 0:
        return {
            "status": "unsupported",
            "reason": "sensitivity_has_no_decisive_samples",
            "p_cond": probability,
        }
    variance = probability * (1.0 - probability) / decisive_count
    variance += p_repeat * (1.0 - p_repeat) / repeat_decisive
    difference = abs(probability - p_repeat)
    threshold = 3.0 * math.sqrt(max(0.0, variance)) + 0.001
    return {
        "status": "scored",
        "p_cond": probability,
        "repeat_p_cond": p_repeat,
        "difference": difference,
        "threshold": threshold,
        "flagged": difference > threshold,
        "base_decisive_draws": decisive_count,
        "repeat_draws": 20000,
        "repeat_decisive_draws": int(repeat_decisive),
        "seed": repeat.seed,
    }


def _mean(values):
    return float(np.mean(values)) if values else None


def _score_summary(scores):
    return {
        "n": len(scores),
        "brier": _mean([row["brier"] for row in scores]),
        "log_loss": _mean([row["log_loss"] for row in scores]),
        "clipped_log_losses": sum(row["clipped"] for row in scores),
        "unclipped_probability_min": min((row["unclipped_p"] for row in scores), default=None),
        "unclipped_probability_max": max((row["unclipped_p"] for row in scores), default=None),
    }


def _paired_comparison(model_scores, market_scores):
    common = sorted(set(model_scores) & set(market_scores))
    rows = []
    for game_id in common:
        model = model_scores[game_id]
        market = market_scores[game_id]
        rows.append(
            {
                "game_id": game_id,
                "season": model["season"],
                "week": model["week"],
                "game_type": model["game_type"],
                "kickoff": model["kickoff"],
                "brier_difference": model["loss"]["brier"] - market["brier"],
                "log_loss_difference": model["loss"]["log_loss"] - market["log_loss"],
            }
        )
    from lab.eval.score_metrics import paired_bootstrap

    result = {"n": len(rows), "game_ids": common}
    for metric in ("brier", "log_loss"):
        metric_rows = [
            {**row, "difference": row[f"{metric}_difference"]} for row in rows
        ]
        inference = paired_bootstrap(metric_rows)
        mean_difference = inference.pop("mean")
        result[metric] = {
            **inference,
            "model_minus_reference": mean_difference,
            "per_season_difference": {
                str(year): _mean(
                    [row[f"{metric}_difference"] for row in rows if row["season"] == year]
                )
                for year in sorted({row["season"] for row in rows})
            },
        }
    return result


def evaluate_saved_run(run_dir, odds_manifest_path):
    """Score the evaluator-only reference from a complete, hash-verified saved run."""
    run_dir, odds_manifest_path = Path(run_dir), Path(odds_manifest_path)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("completed RF-001 manifest required")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("status") != "complete":
        raise ValueError("RF-001 runner must complete before reference evaluation")
    _model_seasons(manifest)  # Fail closed before opening predictions/evaluation outcomes.
    predictions_path = _safe_run_file(run_dir, "predictions.jsonl")
    predictions_bytes = predictions_path.read_bytes()
    if hashlib.sha256(predictions_bytes).hexdigest() != manifest.get("predictions_hash"):
        raise ValueError("saved predictions changed after hash verification")
    predictions = _read_jsonl_bytes(predictions_bytes, predictions_path.name)
    evaluation_path = _safe_run_file(run_dir, "evaluation.json")
    metrics_path = _safe_run_file(run_dir, "metrics.json")
    evaluation_bytes = evaluation_path.read_bytes()
    metrics_bytes = metrics_path.read_bytes()
    evaluation = json.loads(evaluation_bytes)
    metric_report = json.loads(metrics_bytes)
    if not isinstance(evaluation, list):
        raise TypeError("saved evaluation must be a JSON array")
    odds_manifest_path = Path(odds_manifest_path)
    odds_manifest_bytes = odds_manifest_path.read_bytes()
    odds_manifest = json.loads(odds_manifest_bytes)
    odds = load_odds_partitions(odds_manifest_path)

    models = ("rf001", "league", "elo", "home_rate", "half")
    prediction_by_key, evaluation_by_key = {}, {}
    for row in predictions:
        if row.get("role") != "outer" or row.get("model") not in models:
            continue
        season = int(row.get("season", -1))
        if season not in OUTER_SEASONS:
            if season >= 2024:
                raise ValueError("saved predictions contain holdout seasons")
            continue
        key = (row["game_id"], row["model"])
        if key in prediction_by_key:
            raise ValueError("duplicate model prediction for game ID")
        prediction_by_key[key] = row

    outcome_by_id = {}
    for row in evaluation:
        if row.get("role") != "outer" or row.get("model") not in models:
            continue
        season = int(row.get("season", -1))
        if season not in OUTER_SEASONS:
            if season >= 2024:
                raise ValueError("saved evaluation contains holdout seasons")
            continue
        key = (row["game_id"], row["model"])
        if key in evaluation_by_key:
            raise ValueError("duplicate scored prediction for game ID")
        prediction = prediction_by_key.get(key)
        if prediction is None or prediction.get("status") not in ("forecast", "fallback"):
            raise ValueError("evaluation row has no saved forecast/fallback prediction")
        if row.get("status") != prediction.get("status"):
            raise ValueError("prediction/evaluation status mismatch")
        y = _outcome(row)
        if row.get("season") != prediction.get("season"):
            raise ValueError("prediction/evaluation season mismatch")
        if row["game_id"] in outcome_by_id and outcome_by_id[row["game_id"]] != y:
            raise ValueError("conflicting saved outcomes by game ID")
        outcome_by_id[row["game_id"]] = y
        evaluation_by_key[key] = row

    outer_targets = {
        row["game_id"]: row
        for (game_id, model), row in prediction_by_key.items()
        if model == "rf001"
    }
    outer_ids = set(outer_targets)
    odds_states = {
        game_id: odds.get(game_id, {}).get("proportional", {"status": "missing_pair"})
        for game_id in outer_ids
    }
    valid_ids = {
        game_id for game_id, quote in odds_states.items() if quote.get("status") == "ok"
    }
    tie_ids = {game_id for game_id in valid_ids if outcome_by_id.get(game_id) == 0.5}
    missing_label_ids = {game_id for game_id in valid_ids if game_id not in outcome_by_id}
    primary_ids = {
        game_id
        for game_id in valid_ids
        if outcome_by_id.get(game_id) in (0.0, 1.0)
        and outer_targets[game_id]["season"] in OUTER_SEASONS
    }

    market_scores, power_scores = {}, {}
    market_probabilities = []
    for game_id in sorted(primary_ids):
        y = outcome_by_id[game_id]
        quote = odds[game_id]
        proportional = quote["proportional"]
        loss = binary_score(proportional["p_home"], y)
        market_scores[game_id] = {"brier": loss["brier"], "log_loss": loss["log_loss"]}
        market_probabilities.append(proportional["p_home"])
        power = quote["power"]
        if power.get("status") == "ok":
            power_scores[game_id] = binary_score(power["p_home"], y)
    model_reports, model_score_maps = {}, {}
    for model in models:
        predictions_for_model = {
            game_id: row
            for (game_id, model_name), row in prediction_by_key.items()
            if model_name == model
        }
        scores = {}
        mc_rows = []
        for game_id in sorted(primary_ids):
            prediction = predictions_for_model.get(game_id)
            evaluated = evaluation_by_key.get((game_id, model))
            if prediction is None or prediction.get("status") not in ("forecast", "fallback") or evaluated is None:
                continue
            if model in ("rf001", "league"):
                probability = conditional_home_probability(
                    evaluated.get("p_home"), evaluated.get("p_away")
                )
            else:
                probability = evaluated.get("p_share")
            if probability is None:
                continue
            loss = binary_score(probability, outcome_by_id[game_id])
            scores[game_id] = {
                "loss": loss,
                "season": int(evaluated["season"]),
                "week": int(evaluated["week"]),
                "game_type": evaluated["game_type"],
                "kickoff": evaluated["kickoff"],
                "status": prediction["status"],
                "probability": probability,
            }
            if model in ("rf001", "league"):
                mc = _read_distribution(
                    run_dir,
                    prediction,
                    {
                        **evaluated,
                        "game_id": game_id,
                        "run_seed": manifest["config"]["run_seed"],
                    },
                )
                if mc.get("status") == "scored" and not math.isclose(
                    mc["p_cond"], probability, abs_tol=1e-12
                ):
                    raise ValueError("conditional probability disagrees with saved samples")
                mc_rows.append({"game_id": game_id, **mc})
        model_score_maps[model] = scores
        aggregate = _score_summary([value["loss"] for value in scores.values()])
        if model in ("elo", "home_rate"):
            aggregate["probability_interpretation"] = (
                "Saved scalar scored unadjusted as an approximation to the conditional decisive-game "
                "win probability; no separately identified tie probability."
            )
        aggregate.update(
            by_season={
                str(year): _score_summary(
                    [value["loss"] for value in scores.values() if value["season"] == year]
                )
                for year in sorted({value["season"] for value in scores.values()})
            },
            game_ids=sorted(scores),
            candidate_predictions=sum(
                row.get("status") == "forecast" for row in predictions_for_model.values()
            ) if model == "rf001" else None,
            fallback_predictions=sum(
                row.get("status") == "fallback" for row in predictions_for_model.values()
            ) if model == "rf001" else None,
            candidate_predictions_primary=sum(
                predictions_for_model.get(game_id, {}).get("status") == "forecast"
                for game_id in primary_ids
            ) if model == "rf001" else None,
            fallback_predictions_primary=sum(
                predictions_for_model.get(game_id, {}).get("status") == "fallback"
                for game_id in primary_ids
            ) if model == "rf001" else None,
            candidate_scored_primary=sum(
                scores.get(game_id, {}).get("status") == "forecast"
                for game_id in primary_ids
            ) if model == "rf001" else None,
            fallback_scored_primary=sum(
                scores.get(game_id, {}).get("status") == "fallback"
                for game_id in primary_ids
            ) if model == "rf001" else None,
            missing_predictions=sum(
                predictions_for_model.get(game_id, {}).get("status")
                not in ("forecast", "fallback")
                for game_id in primary_ids
            ),
            unsupported_probabilities=sum(
                predictions_for_model.get(game_id, {}).get("status") in ("forecast", "fallback")
                and game_id not in scores
                for game_id in primary_ids
            ),
            model_mean_probability=_mean([value["probability"] for value in scores.values()]),
            monte_carlo_sensitivity={
                "status": "scored" if mc_rows and all(row["status"] == "scored" for row in mc_rows) else "partial_or_unsupported",
                "draws": 20000,
                "seed_namespace": "mc-sensitivity-v1",
                "rows": mc_rows,
                "flagged": sum(row.get("flagged", False) for row in mc_rows),
                "maximum_difference": max((row.get("difference", 0.0) for row in mc_rows), default=None),
            } if model in ("rf001", "league") else None,
        )
        power_common = set(scores) & set(power_scores)
        aggregate["power_sensitivity"] = _paired_comparison(
            scores, power_scores
        ) if power_common else {"n": 0, "game_ids": []}
        model_reports[model] = aggregate

    registered_pairs = {}
    for model, comparison in metric_report.get("comparisons", {}).items():
        if model in models and isinstance(comparison, dict):
            ids = comparison.get("common_game_ids", [])
            registered_pairs[model] = list(ids)
    all_model_common = set(primary_ids)
    for model in models:
        all_model_common &= set(model_score_maps[model])

    market_summary = _score_summary(
        [binary_score(odds[gid]["proportional"]["p_home"], outcome_by_id[gid]) for gid in sorted(primary_ids)]
    )
    market_summary.update(
        p_home_mean=_mean(market_probabilities),
        label=REFERENCE_LABEL,
        population="decisive completed outer games with valid paired moneylines",
        assumption="normalized two-way odds are conditional decisive-game win probabilities",
        limitations=["timing unknown", "book/aggregation unknown", "settlement semantics unknown"],
        power_sensitivity=_score_summary(list(power_scores.values())),
    )
    return {
        "schema": "rf001-moneyline-evaluation-v1",
        "label": REFERENCE_LABEL,
        "source_assumption": "normalized two-way odds represent conditional decisive-game win probabilities",
        "historical_accuracy_claim": False,
        "market_superiority_claim": False,
        "strict_historical_point_in_time_claim": False,
        "provenance": {
            "runner_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "predictions_sha256": hashlib.sha256(predictions_bytes).hexdigest(),
            "evaluation_sha256": hashlib.sha256(evaluation_bytes).hexdigest(),
            "metrics_sha256": hashlib.sha256(metrics_bytes).hexdigest(),
            "odds_manifest_sha256": hashlib.sha256(odds_manifest_bytes).hexdigest(),
            "runner_provenance": manifest.get("provenance", {}),
            "odds_source": odds_manifest["source"],
            "odds_extraction": odds_manifest["extraction"],
            "source_commit": odds_manifest["source"]["commit"],
            "source_sha256": odds_manifest["source"]["sha256"],
        },
        "coverage": {
            "outer_games": len(outer_ids),
            "outer_games_with_saved_labels": len(outer_ids & set(outcome_by_id)),
            "valid_moneyline_pairs": len(valid_ids),
            "primary_decisive_games": len(primary_ids),
            "ties_excluded": len(tie_ids),
            "valid_odds_missing_labels": len(missing_label_ids),
            "missing_pairs": sum(state["status"] == "missing_pair" for state in odds_states.values()),
            "partial_pairs": sum(state["status"] == "partial_pair" for state in odds_states.values()),
            "invalid_pairs": sum(state["status"] == "invalid_pair" for state in odds_states.values()),
            "excluded_non_outer_odds_rows": sum(row["season"] not in OUTER_SEASONS for row in odds.values()),
            "tie_game_ids": sorted(tie_ids),
            "missing_moneyline_game_ids": sorted(
                game_id for game_id, state in odds_states.items()
                if state["status"] in ("missing_pair", "partial_pair", "invalid_pair")
            ),
            "valid_odds_missing_label_game_ids": sorted(missing_label_ids),
        },
        "market": market_summary,
        "models": model_reports,
        "pairwise_market_comparisons": {
            model: _paired_comparison(
                {gid: {**value, "loss": value["loss"]} for gid, value in model_score_maps[model].items()},
                market_scores,
            )
            for model in models
        },
        "registered_football_pairwise_populations": registered_pairs,
        "all_model_complete_case_descriptive": {"n": len(all_model_common), "game_ids": sorted(all_model_common)},
        "bootstrap": {"replicates": 5000, "seed": 20261008, "comparison": "model minus reference Brier"},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract", help="create immutable 2006–2023 odds partitions")
    extract.add_argument("--source", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--source-commit", default=SOURCE_COMMIT)
    extract.add_argument("--expected-source-sha256", default=SOURCE_SHA256)
    evaluate = subparsers.add_parser("evaluate", help="score saved RF-001 predictions only")
    evaluate.add_argument("--run-dir", type=Path, required=True)
    evaluate.add_argument("--odds-manifest", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "extract":
        result = extract_odds_partitions(
            args.source,
            args.output,
            source_commit=args.source_commit,
            expected_source_sha256=args.expected_source_sha256,
        )
        print(json.dumps({"output": str(args.output), "partitions": len(result["partitions"])}))
        return
    result = evaluate_saved_run(args.run_dir, args.odds_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
