"""Offline RF-001 development runner. Run with an explicit audited local manifest.

    PYTHON_DOTENV_DISABLED=1 uv run python -m lab.backtest.nfl_score \
        --manifest data/research/inputs/manifest.json --run-id development-001

There is deliberately no download function or holdout override.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
import subprocess
import sys
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import duckdb
import numpy as np

from lab.backtest.score_artifacts import RecordStore, observation_root, record_ref
from lab.backtest.score_data import (
    ALIAS_VERSION,
    FINISH_LAG,
    Game,
    canonical,
    digest,
    load_manifest,
    stamp,
    validate_execution_policy,
    validate_population,
)
from lab.eval.score_metrics import (
    crps,
    paired_bootstrap,
    probability_losses,
    score_draws,
    select_setting,
)
from lab.features import nfl as frozen
from lab.models.nfl_score import (
    DistributionUnavailable,
    FitUnavailable,
    fit_score,
    sample_scores,
    stable_seed,
)

ROOT = Path(__file__).resolve().parents[3]
GRID = tuple(
    (penalty, half_life) for penalty in (0.0003, 0.001, 0.003) for half_life in (365, 730, None)
)
MODELS = ("rf001", "league", "elo", "home_rate", "half")


def recipe_name(setting):
    return "league" if setting is None else f"ridge-{setting[0]}-half-{setting[1]}"


class ChronologicalEngine:
    """Receives a score-free target and eligible prior observations only.

    Means from prior T-24h fits stay immutable; eligible current label revisions
    form residuals against those means, independently for every recipe.
    """

    def __init__(self):
        self.means = {}
        self.current_key = None
        self.current_fits = {}
        self.input_signatures = {}
        self.last_as_of = None

    def _fit(self, game, prior, setting):
        recipe = recipe_name(setting)
        if recipe in self.current_fits:
            return self.current_fits[recipe]
        if len(prior) < 100:
            result = None
        else:
            try:
                result = fit_score(
                    prior, game.as_of, *(setting or (1, None)), league=setting is None
                )
            except FitUnavailable:
                result = None
        self.current_fits[recipe] = result
        if result is not None:
            value = {
                "means": result.predict(game.home_team, game.away_team, game.location == "Neutral"),
                "as_of": stamp(game.as_of),
                "input_hash": result.audit["input_hash"],
                "n_games": result.audit["n_games"],
                "schedule_revision": game.vintage.revision_id,
                "schedule_ref": record_ref(game),
                "fit_path": f"fits/{digest(result.audit)}.json",
            }
            self.means.setdefault(recipe, {})[game.game_id] = value
        return result

    def _bank(self, prior, setting):
        recipe = recipe_name(setting)
        saved = self.means.get(recipe, {})
        bank = []
        for obs in prior:
            mean = saved.get(obs.game.game_id)
            if mean is None:
                continue
            bank.append(
                {
                    "game_id": obs.game.game_id,
                    "kickoff": stamp(obs.game.kickoff),
                    "recipe": recipe,
                    "fit_as_of": mean["as_of"],
                    "fit_input_hash": mean["input_hash"],
                    "fit_schedule_revision": mean["schedule_revision"],
                    "fit_schedule_ref": mean["schedule_ref"],
                    "fit_path": mean["fit_path"],
                    "prior_means": list(mean["means"]),
                    "label_revision": obs.label.revision_id,
                    "label_ref": record_ref(obs.label),
                    "residual": [
                        obs.label.home_score - mean["means"][0],
                        obs.label.away_score - mean["means"][1],
                    ],
                }
            )
        return bank

    def predict(self, game, observations, setting, run_seed, *, league_only=False):
        if not isinstance(game, Game):
            raise TypeError("score-free Game target required")
        if len({o.game.game_id for o in observations}) != len(observations):
            raise ValueError("duplicate game versions in prior observations")
        if self.last_as_of is not None and game.as_of < self.last_as_of:
            raise ValueError("chronological prediction order required")
        prior = sorted(
            (o for o in observations if o.game.season >= 2006),
            key=lambda o: (o.game.kickoff, o.game.game_id),
        )
        key = (game.game_id, game.as_of)
        signature = (record_ref(game), observation_root(prior))
        if key in self.input_signatures and self.input_signatures[key] != signature:
            raise ValueError("changed target/prior inputs at an already cached cutoff")
        self.input_signatures[key] = signature
        self.last_as_of = game.as_of
        if key != self.current_key:
            self.current_key, self.current_fits = key, {}
        if any(
            o.game.game_id == game.game_id or o.game.kickoff + FINISH_LAG >= game.as_of
            for o in prior
        ):
            raise ValueError("target/future score in eligible prior history")
        base = {
            "game_id": game.game_id,
            "as_of": stamp(game.as_of),
            "status": "miss",
            "reason": "insufficient_training",
            "actual_model": None,
            "distribution": None,
            "fit": None,
            "candidate_fit": None,
        }
        league_fit = self._fit(game, prior, None)
        candidate_fit = None if league_only else self._fit(game, prior, setting)
        mean_fit = league_fit if league_only else candidate_fit
        base["mean_fit"] = mean_fit.audit if mean_fit else None
        base["league_fit"] = league_fit.audit if league_fit else None
        base["mean_points"] = (
            mean_fit.predict(game.home_team, game.away_team, game.location == "Neutral")
            if mean_fit
            else None
        )
        base["candidate_fit"] = candidate_fit.audit if candidate_fit else None
        for candidate in [False] if league_only else [True, False]:
            fit = candidate_fit if candidate else league_fit
            bank = self._bank(prior, setting if candidate else None)
            if fit is None:
                if candidate and len(prior) >= 100:
                    base["reason"] = "candidate_fit_unavailable"
                continue
            if len(bank) < 50:
                if candidate:
                    base["reason"] = "insufficient_candidate_residuals"
                elif league_only:
                    base["reason"] = "insufficient_league_residuals"
                continue
            try:
                distribution = sample_scores(
                    fit.predict(game.home_team, game.away_team, game.location == "Neutral"),
                    bank,
                    game.game_id,
                    game.as_of,
                    run_seed,
                    game.game_type,
                )
            except DistributionUnavailable:
                if candidate:
                    base["reason"] = "candidate_distribution_unavailable"
                elif league_only:
                    base["reason"] = "league_distribution_unavailable"
                continue
            base.update(
                status="forecast" if candidate or league_only else "fallback",
                actual_model="opponent-score-v1" if candidate else "league-score-v1",
                reason=None if candidate or league_only else base["reason"],
                distribution=distribution,
                fit=fit.audit,
            )
            return base
        return base


class RunWriter:
    def __init__(self, output_root, run_id):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", run_id):
            raise ValueError("unsafe run_id")
        root = Path(output_root).resolve()
        if "forecasts" in root.parts:
            raise ValueError("research outputs cannot enter forecasts")
        self.path = root / run_id
        self.path.mkdir(parents=True, exist_ok=False)
        self.predictions = self.events = None
        try:
            self.predictions = (self.path / "predictions.jsonl").open("x")
            self.events = (self.path / "events.jsonl").open("x")
            self.store = RecordStore(self.path)
        except BaseException as exc:
            self.failure(exc)
            self.close()
            raise

    def failure(self, exception):
        # Preserve the original exception even if the disk can no longer accept writes.
        try:
            self.json("failure.json", {"status": "failed", "exception": type(exception).__name__})
        except OSError:
            pass

    def json(self, name, value):
        path = self.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as handle:
            handle.write(canonical(value) + "\n")
        return name

    def audit(self, value):
        name = f"fits/{digest(value)}.json"
        if not (self.path / name).exists():
            self.json(name, value)
        return name

    def save(self, row, output=None):
        row = dict(row)
        if output is not None:
            if output.get("league_fit"):
                self.audit(output["league_fit"])
            if output.get("mean_fit"):
                row["mean_fit_path"] = self.audit(output["mean_fit"])
                row["fitted_home_mean"], row["fitted_away_mean"] = output["mean_points"]
            if output.get("candidate_fit"):
                row["candidate_fit_path"] = self.audit(output["candidate_fit"])
            if output.get("fit"):
                row["fit_path"] = self.audit(output["fit"])
                row["input_hash"] = output["fit"]["input_hash"]
                row["training_cutoff"] = output["fit"]["as_of"]
                row["training_games"] = output["fit"]["n_games"]
            dist = output.get("distribution")
            if dist is not None:
                artifact_id = digest(
                    {
                        "samples": hashlib.sha256(dist.samples.tobytes()).hexdigest(),
                        "shape": list(dist.samples.shape),
                        "dtype": dist.samples.dtype.str,
                    }
                )
                sample_name = f"samples/{artifact_id}.npz"
                (self.path / "samples").mkdir(exist_ok=True)
                if not (self.path / sample_name).exists():
                    with (self.path / sample_name).open("xb") as handle:
                        np.savez_compressed(handle, samples=dist.samples)
                bank_name = self.store.bank(dist.bank)
                unique, counts = np.unique(dist.samples, axis=0, return_counts=True)
                table = [
                    [int(h), int(a), int(n), float(n / len(dist.samples))]
                    for (h, a), n in zip(unique, counts, strict=True)
                ]
                table_name = f"probabilities/{artifact_id}.json"
                if not (self.path / table_name).exists():
                    self.json(table_name, table)
                row.update(
                    dist.summary,
                    samples_path=sample_name,
                    bank_path=bank_name,
                    probability_table_path=table_name,
                    seed=dist.seed,
                    rejected_ties=dist.rejected,
                    attempts=dist.attempts,
                    samples_hash=hashlib.sha256((self.path / sample_name).read_bytes()).hexdigest(),
                    reservoir_hash=Path(bank_name).stem,
                    reservoir_size=len(dist.bank),
                )
        self.predictions.write(canonical(row) + "\n")
        self.predictions.flush()
        return row

    def event(self, game_id, event):
        self.events.write(canonical({"game_id": game_id, "event": event}) + "\n")
        self.events.flush()

    def close(self):
        for handle in (self.predictions, self.events):
            if handle is not None:
                handle.close()


def frozen_predictions(observations, game):
    """Filter vintages externally; replay the existing frozen functions unchanged."""
    with duckdb.connect(":memory:") as con:
        con.execute("""CREATE TABLE nfl_game(game_id VARCHAR, season INTEGER, home_team VARCHAR,
                    away_team VARCHAR, home_score INTEGER, away_score INTEGER,
                    location VARCHAR, kickoff_ts TIMESTAMP)""")
        if observations:
            con.executemany(
                "INSERT INTO nfl_game VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        o.game.game_id,
                        o.game.season,
                        o.game.home_team,
                        o.game.away_team,
                        o.label.home_score,
                        o.label.away_score,
                        o.game.location,
                        o.game.kickoff.replace(tzinfo=None),
                    ]
                    for o in observations
                ],
            )
        elo = frozen.win_prob(
            con, game.home_team, game.away_team, game.as_of, game.season, game.location == "Neutral"
        )
        try:
            rate = frozen.home_rate_baseline(con, game.as_of, game.location == "Neutral")
        except ValueError:
            rate = None
    return {"elo": elo, "home_rate": rate, "half": 0.5}


def provenance():
    paths = [
        "src/lab/backtest/score_data.py",
        "src/lab/backtest/nfl_score.py",
        "src/lab/backtest/score_artifacts.py",
        "src/lab/models/nfl_score.py",
        "src/lab/eval/score_metrics.py",
        "src/lab/features/nfl.py",
        "src/lab/models/nfl_elo.py",
        "src/lab/store/asof.py",
        "research/evaluation_protocol.md",
        "pyproject.toml",
        "uv.lock",
    ]
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    patch = subprocess.check_output(["git", "diff", "HEAD", "--", *paths], cwd=ROOT)
    return {
        "git_sha": sha,
        "dirty_patch_hash": hashlib.sha256(patch).hexdigest(),
        "working_file_hashes": hashes,
        "working_code_hash": digest(hashes),
        "python": sys.version,
        "numpy": np.__version__,
        "dependencies": {name: version(name) for name in ("numpy", "duckdb", "polars")},
        "numpy_build": np.show_config(mode="dicts")["Build Dependencies"],
        "alias_version": ALIAS_VERSION,
        "uv_lock_hash": hashes["uv.lock"],
        "artifact_schema": "rf001-v2",
    }


def split_role(season):
    return (
        "baseline_warmup"
        if season < 2006
        else "warmup"
        if season < 2012
        else ("inner_only" if season < 2015 else "outer")
    )


def _base_row(game, model, cohort, *, status="forecast", actual_model=None, reason=None):
    return {
        "game_id": game.game_id,
        "season": game.season,
        "week": game.week,
        "game_type": game.game_type,
        "kickoff": stamp(game.kickoff),
        "as_of": stamp(game.as_of),
        "location": game.location,
        "home_team": game.home_team,
        "away_team": game.away_team,
        "model": model,
        "model_version": "rf001-v2",
        "cohort": cohort,
        "role": split_role(game.season),
        "status": status,
        "reason": reason,
        "actual_model": actual_model,
        "reconstruction": cohort == "reconstructed_scores",
        "schedule_revision": game.vintage.revision_id,
        "schedule_ref": record_ref(game),
        "schedule_hash": digest(game),
        "missing_inputs": False,
    }


def tune_at_cutoff(saved_trials, prior, writer, outer_season):
    labels = {o.game.game_id: o.label for o in prior}
    trials = []
    # Compare the nine raw candidate recipes on common available inner games.
    ids = [
        {
            r["game_id"]
            for r in saved_trials[setting]
            if 2012 <= r["season"] < outer_season
            and r["game_id"] in labels
            and r["status"] == "forecast"
        }
        for setting in GRID
    ]
    common = set.intersection(*ids) if ids else set()
    for setting in GRID:
        losses = []
        for row in saved_trials[setting]:
            if row["game_id"] not in common or not 2012 <= row["season"] < outer_season:
                continue
            label = labels[row["game_id"]]
            with np.load(writer.path / row["samples_path"]) as archive:
                samples = archive["samples"]
            losses.append(
                {
                    "game_id": row["game_id"],
                    "season": row["season"],
                    "label_revision": label.revision_id,
                    "margin_crps": crps(
                        samples[:, 0] - samples[:, 1], label.home_score - label.away_score
                    ),
                }
            )
        trials.append({"penalty": setting[0], "half_life": setting[1], "losses": losses})
    selected, ledger = select_setting(trials, outer_season)
    for row, trial in zip(ledger, trials, strict=True):
        row["losses"] = trial["losses"]
        row["selection_cutoff"] = stamp(prior[-1].game.as_of) if prior else None
        row["selected"] = (row["penalty"], row["half_life"]) == selected
        row["common_game_ids"] = sorted(common)
    return selected, ledger


def sensitivity(output, game, observed, run_seed):
    dist = output["distribution"]
    if dist is None:
        return None
    means = (dist.summary["fitted_home_mean"], dist.summary["fitted_away_mean"])
    alternate_seed = stable_seed(run_seed, game.game_id, game.as_of, "mc-sensitivity-v1")
    try:
        repeat = sample_scores(
            means,
            dist.bank,
            game.game_id,
            game.as_of,
            alternate_seed,
            game.game_type,
            n_draws=20000,
        )
    except DistributionUnavailable:
        return {"status": "distribution_unavailable", "run_seed": alternate_seed}
    probabilities = {}
    for name in ("p_home", "p_away", "p_tie", "p_share"):
        a, b = dist.summary[name], repeat.summary[name]
        # For share, X takes 0,.5,1; use its empirical variance rather than a
        # Bernoulli approximation when ties exist.
        variance_a = (
            a * (1 - a)
            if name != "p_share"
            else (dist.summary["p_home"] + 0.25 * dist.summary["p_tie"] - a * a)
        )
        variance_b = (
            b * (1 - b)
            if name != "p_share"
            else (repeat.summary["p_home"] + 0.25 * repeat.summary["p_tie"] - b * b)
        )
        limit = 3 * math.sqrt(max(0, variance_a) / 10000 + max(0, variance_b) / 20000) + 0.001
        probabilities[name] = {
            "difference": abs(a - b),
            "threshold": limit,
            "flagged": abs(a - b) > limit,
        }
    scores = {}
    if observed is not None:
        for name, samples, other, label in (
            (
                "margin_crps",
                dist.samples[:, 0] - dist.samples[:, 1],
                repeat.samples[:, 0] - repeat.samples[:, 1],
                observed[0] - observed[1],
            ),
            ("total_crps", dist.samples.sum(axis=1), repeat.samples.sum(axis=1), sum(observed)),
        ):
            difference = abs(crps(samples, label) - crps(other, label))
            scores[name] = {"difference": difference, "flagged": difference > 0.1}
    return {
        "status": "scored",
        "run_seed": alternate_seed,
        "seed": repeat.seed,
        "draws": 20000,
        "probabilities": probabilities,
        "scores": scores,
    }


def _aggregate(rows, all_rows, labels):
    attempted = len(all_rows)
    excluded = sum(r["status"] == "exclusion" for r in all_rows)
    missed = sum(r["status"] == "miss" for r in all_rows)
    predicted = attempted - excluded - missed
    metric_keys = (
        "brier",
        "log_loss",
        "margin_crps",
        "total_crps",
        "energy",
        "energy_sensitivity",
        "three_way_brier",
        "three_way_log_loss",
        "exact_score_mass",
    )
    result = {
        "attempted": attempted,
        "eligible": attempted - excluded,
        "predicted": predicted,
        "fallback": sum(r["status"] == "fallback" for r in all_rows),
        "missed": missed,
        "excluded": excluded,
        "scored": len(rows),
        "unlabelled": predicted - len(rows),
        "coverage": predicted / (attempted - excluded) if attempted > excluded else None,
        "promotion_coverage_gate": missed == 0
        and excluded == 0
        and bool(attempted)
        and len(rows) == predicted,
        "conditional_on_saved_predictions": True,
        "reasons": {
            reason: sum(r.get("reason") == reason for r in all_rows)
            for reason in sorted({r["reason"] for r in all_rows if r.get("reason")})
        },
    }
    for key in metric_keys:
        values = [r[key] for r in rows if key in r]
        result[key] = float(np.mean(values)) if values else None
    for team in ("home", "away", "margin", "total"):
        for suffix in ("mae", "bias", "pit"):
            values = [r[f"{team}_{suffix}"] for r in rows if f"{team}_{suffix}" in r]
            result[f"{team}_{suffix}"] = float(np.mean(values)) if values else None
        pits = [r[f"{team}_pit"] for r in rows if f"{team}_pit" in r]
        result[f"{team}_pit_histogram"] = np.histogram(pits, bins=np.linspace(0, 1, 11))[0].tolist()
        squares = [r[f"{team}_squared_error"] for r in rows if f"{team}_squared_error" in r]
        result[f"{team}_rmse"] = float(np.sqrt(np.mean(squares))) if squares else None
        for level in (50, 80, 95):
            for suffix in ("covered", "width"):
                key = f"{team}_{level}_{suffix}"
                values = [r[key] for r in rows if key in r]
                result[key] = float(np.mean(values)) if values else None
    result["log_loss_clipped"] = sum(r.get("clipped", 0) for r in rows)
    result["three_way_clipped"] = sum(r.get("three_way_clipped", 0) for r in rows)
    result["ties"] = sum(r["y"] == 0.5 for r in rows)
    result["unclipped_extremes"] = sum(r["p_share"] in (0, 1) for r in rows)
    bins = []
    for i in range(10):
        values = [r for r in rows if min(9, int(r["p_share"] * 10)) == i]
        bins.append(
            {
                "bin": i,
                "n": len(values),
                "p": float(np.mean([r["p_share"] for r in values])) if values else None,
                "y": float(np.mean([r["y"] for r in values])) if values else None,
            }
        )
    result["calibration_deciles"] = bins
    loss_sum = sum(r["brier"] for r in rows)
    unscored = [
        r
        for r in all_rows
        if r["status"] != "exclusion" and r["game_id"] not in {x["game_id"] for x in rows}
    ]
    maximum = 0
    for row in unscored:
        label = labels.get(row["game_id"])
        maximum += 0.25 if label and label.home_score == label.away_score else 1
    denominator = attempted - excluded
    result["brier_eligible_bounds"] = (
        [loss_sum / denominator, (loss_sum + maximum) / denominator] if denominator else None
    )
    return result


def metric_report(
    predictions,
    evaluated,
    labels,
    *,
    synthetic,
    population_accounting=None,
    external_population_exclusions=(),
):
    outer_pred = [p for p in predictions if p["model"] in MODELS and p["role"] == "outer"]
    outer_eval = [p for p in evaluated if p["model"] in MODELS and p["role"] == "outer"]
    report = {
        "synthetic": synthetic,
        "historical_accuracy_claim": False,
        "population_accounting": population_accounting,
        "external_population_exclusions": list(external_population_exclusions),
        "market_mid": {"status": "unavailable_no_same_cutoff_quotes"},
        "primary_probability": "home-result-share Brier",
        "primary_distribution": "margin CRPS (empirical V-statistic)",
        "outer": {},
        "per_season": {},
        "slices": {},
        "comparisons": {},
    }
    for model in MODELS:
        all_rows = [r for r in outer_pred if r["model"] == model]
        scored = [r for r in outer_eval if r["model"] == model]
        report["outer"][model] = _aggregate(scored, all_rows, labels)
        report["per_season"][model] = {
            str(season): _aggregate(
                [r for r in scored if r["season"] == season],
                [r for r in all_rows if r["season"] == season],
                labels,
            )
            for season in sorted({r["season"] for r in all_rows})
        }
        groups = {
            "early_regular": lambda r: r.get("game_type") == "REG" and r.get("week", 0) <= 4,
            "later_regular": lambda r: r.get("game_type") == "REG" and r.get("week", 0) > 4,
            "postseason": lambda r: r.get("game_type") not in (None, "REG"),
            "neutral": lambda r: r.get("location") == "Neutral",
            "home_site": lambda r: r.get("location") == "Home",
            "rest_under_6": lambda r: r.get("short_rest") is True,
            "rest_6_or_more": lambda r: r.get("short_rest") is False,
            "rest_unknown": lambda r: r.get("short_rest") is None,
            "missing_inputs": lambda r: r.get("missing_inputs") is True,
            "inputs_present": lambda r: r.get("missing_inputs") is False,
        }
        report["slices"][model] = {
            name: _aggregate(
                [r for r in scored if test(r)], [r for r in all_rows if test(r)], labels
            )
            for name, test in groups.items()
        }
    candidate = {r["game_id"]: r for r in outer_eval if r["model"] == "rf001"}
    for model in MODELS[1:]:
        baseline = {r["game_id"]: r for r in outer_eval if r["model"] == model}
        common = sorted(candidate.keys() & baseline.keys())
        comparison = {
            "common_game_ids": common,
            "eligible_candidate": report["outer"]["rf001"]["eligible"],
            "eligible_baseline": report["outer"][model]["eligible"],
            "scored_candidate": len(candidate),
            "scored_baseline": len(baseline),
        }
        for metric in ("brier", "log_loss", "margin_crps", "total_crps"):
            rows = []
            for gid in common:
                a, b = candidate[gid], baseline[gid]
                if metric not in a or metric not in b:
                    continue
                rows.append(
                    {
                        "game_id": gid,
                        "season": a["season"],
                        "week": a["week"],
                        "game_type": a["game_type"],
                        "kickoff": a["kickoff"],
                        "difference": a[metric] - b[metric],
                    }
                )
            value = paired_bootstrap(rows)
            value["per_season"] = {
                str(y): float(np.mean([r["difference"] for r in rows if r["season"] == y]))
                for y in sorted({r["season"] for r in rows})
            }
            comparison[metric] = value
        denominator = float(np.mean([baseline[g]["brier"] for g in common])) if common else None
        comparison["brier_skill_denominator"] = denominator
        comparison["brier_skill"] = (
            1 - float(np.mean([candidate[g]["brier"] for g in common])) / denominator
            if denominator
            else None
        )
        report["comparisons"][model] = comparison
    return report


def run(manifest_path, output_root=None, run_id="development-001", *, run_seed=20261008):
    dataset, source_manifest = load_manifest(Path(manifest_path), require_execution_policy=True)
    if not source_manifest["synthetic"]:
        if run_seed != 20261008:
            raise ValueError("real run requires the registered seed 20261008")
        validate_execution_policy(source_manifest, required=True)
        for part in source_manifest["partitions"]:
            audit = part.get("audit", {})
            if not audit.get("kickoff_and_label_coverage_reviewed"):
                raise ValueError("real run requires kickoff/label coverage audit")
        post_seasons = {g.season for g in dataset.games if g.game_type != "REG"}
        pinned_rules = source_manifest.get("postseason_rule_metadata", {})
        if any(not pinned_rules.get(str(y)) for y in post_seasons):
            raise ValueError("real postseason requires season-specific pinned rule metadata")
    validate_population(dataset, source_manifest)
    policy = source_manifest.get("execution_policy")
    external_exclusions = policy["external_population_exclusions"] if policy else []
    population_accounting = policy["population_accounting"] if policy else None
    writer = RunWriter(output_root or ROOT / "data/research/runs", run_id)
    try:
        configuration = {
            "cohort": dataset.cohort,
            "revision_clock": dataset.revision_clock,
            "grid": GRID,
            "run_seed": run_seed,
            "mean_gate": 100,
            "residual_gate": 50,
            "draws": 10000,
            "sensitivity_draws": 20000,
            "refit": "each forecast cutoff",
            "bootstrap_replicates": 5000,
            "bootstrap_seed": 20261008,
            "development_seasons": [2006, 2023],
            "outer_seasons": [2015, 2023],
            "inner_start": 2012,
            "final_holdout_access": False,
            "execution_policy_hash": digest(policy) if policy else None,
            "external_population_exclusions_hash": digest(external_exclusions),
        }
        writer.json(
            "started.json",
            {
                "config": configuration,
                "source_manifest": source_manifest,
                "provenance": provenance(),
                "status": "running",
            },
        )
        writer.json("external_population_exclusions.json", external_exclusions)
        predictions, evaluated, trial_ledger, mc_checks = [], [], [], []
        saved_trials = {setting: [] for setting in GRID}
        final_labels, selections = {}, {}
        engine = ChronologicalEngine()
        targets = dataset.targets()
        splits = [
            {
                "game_id": g.game_id,
                "season": g.season,
                "role": split_role(g.season),
                "as_of": stamp(g.as_of),
            }
            for g in targets
        ]
        writer.json("splits.json", splits)
        for exclusion in dataset.exclusions:
            for model in MODELS:
                row = dict(
                    exclusion,
                    model=model,
                    role=split_role(exclusion["season"]),
                    status="exclusion",
                    cohort=dataset.cohort,
                    missing_inputs=True,
                )
                predictions.append(writer.save(row))
        target_ids = {g.game_id for g in targets}
        missing_schedule = sorted(
            {g.game_id for g in dataset.games}
            - target_ids
            - {x["game_id"] for x in dataset.exclusions}
        )
        for gid in missing_schedule:
            game = next(g for g in dataset.games if g.game_id == gid)
            for model in MODELS:
                row = _base_row(
                    game, model, dataset.cohort, status="exclusion", reason="no_proven_T24_schedule"
                )
                row["missing_inputs"] = True
                predictions.append(writer.save(row))
        for game in targets:
            writer.store.put(record_ref(game), {"kind": "Game", "value": game})
            prior = dataset.eligible(game.as_of)
            prior_root = writer.store.observations(prior)
            writer.store.observations([o for o in prior if o.game.season >= 2006])
            if game.season >= 2015 and game.season not in selections:
                choice, ledger = tune_at_cutoff(saved_trials, prior, writer, game.season)
                for row in ledger:
                    row["selection_cutoff"] = stamp(game.as_of)
                selections[game.season] = choice
                trial_ledger.extend(ledger)
            scores_for_game, outputs_for_game = [], []
            for setting in GRID if game.season >= 2006 else ():
                output = engine.predict(game, prior, setting, run_seed)
                raw_status = output["status"] if output["status"] != "fallback" else "miss"
                raw = _base_row(
                    game,
                    recipe_name(setting),
                    dataset.cohort,
                    status=raw_status,
                    actual_model=output["actual_model"] if raw_status == "forecast" else None,
                    reason=output["reason"],
                )
                # Fallback is not the candidate recipe used for tuning.
                raw_output = (
                    output
                    if raw_status == "forecast"
                    else {
                        key: output.get(key)
                        for key in ("candidate_fit", "league_fit", "mean_fit", "mean_points")
                    }
                )
                saved_trials[setting].append(writer.save(raw, raw_output))
                outputs_for_game.append((setting, output))
            league_output = engine.predict(game, prior, None, run_seed, league_only=True)
            choice = selections.get(game.season)
            chosen_output = next((o for s, o in outputs_for_game if s == choice), None)
            if chosen_output is None:
                chosen_output = dict(league_output)
                if chosen_output["status"] == "forecast":
                    chosen_output.update(status="fallback", reason="no_eligible_inner_tuning")
            for model, output in (("rf001", chosen_output), ("league", league_output)):
                row = _base_row(
                    game,
                    model,
                    dataset.cohort,
                    status=output["status"],
                    actual_model=output["actual_model"],
                    reason=output["reason"],
                )
                row["selected_setting"] = choice if model == "rf001" else None
                rest = []
                for team in (game.home_team, game.away_team):
                    previous = [
                        o.game.kickoff
                        for o in prior
                        if team in (o.game.home_team, o.game.away_team)
                    ]
                    rest.append(
                        (game.kickoff - max(previous)).total_seconds() / 86400 if previous else None
                    )
                short_rest = (
                    any(t is not None and t < 6 for t in rest)
                    if (all(t is not None for t in rest))
                    else None
                )
                row["short_rest"] = short_rest
                row["rest_days"] = rest
                row = writer.save(row, output)
                predictions.append(row)
                scores_for_game.append(row)
                outputs_for_game.append((model, output))
            baselines = frozen_predictions(prior, game)
            for model, p in baselines.items():
                row = _base_row(
                    game,
                    model,
                    dataset.cohort,
                    status="forecast" if p is not None else "miss",
                    actual_model={
                        "elo": "elo-538-default-v0",
                        "home_rate": "home-rate-v0",
                        "half": "constant-half-v0",
                    }[model],
                    reason="no_finished_home_games" if p is None else None,
                )
                row.update(
                    short_rest=short_rest,
                    rest_days=rest,
                    p_share=p,
                    input_hash=digest({"observations_root": prior_root}),
                    training_root=prior_root,
                    training_cutoff=stamp(game.as_of),
                    training_games=len(prior),
                    replay_start=min((o.game.season for o in prior), default=None),
                )
                row = writer.save(row)
                predictions.append(row)
                scores_for_game.append(row)
            writer.event(game.game_id, "predictions_saved")
            label = dataset.evaluation_label(game.game_id)
            if label is not None:
                final_labels[game.game_id] = label
                observed = (label.home_score, label.away_score)
                if game.game_type != "REG" and label.home_score == label.away_score:
                    raise ValueError("postseason finalized label is tied")
                for row in scores_for_game:
                    if row["status"] not in ("forecast", "fallback"):
                        continue
                    scored = dict(
                        row,
                        evaluation_label=asdict(label),
                        label_revision=label.revision_id,
                        y=1
                        if label.home_score > label.away_score
                        else (0 if label.home_score < label.away_score else 0.5),
                    )
                    if row["model"] in ("rf001", "league"):
                        with np.load(writer.path / row["samples_path"]) as archive:
                            values = score_draws(
                                archive["samples"],
                                observed,
                                stable_seed(run_seed, game.game_id, game.as_of, "energy-v1"),
                            )
                    else:
                        values = probability_losses(row["p_share"], scored["y"])
                    scored.update(values)
                    evaluated.append(scored)
            else:
                observed = None
            checks_by_inputs = {}
            saved_by_model = {r["model"]: r for r in scores_for_game}
            for model, output in outputs_for_game:
                if model in ("rf001", "league"):
                    row = saved_by_model[model]
                    inputs = (
                        row.get("seed"),
                        row.get("bank_path"),
                        row.get("fitted_home_mean"),
                        row.get("fitted_away_mean"),
                    )
                    if inputs in checks_by_inputs:
                        checks_by_inputs[inputs]["models"].append(model)
                        continue
                    check = sensitivity(output, game, observed, run_seed)
                    if check is not None:
                        record = dict(game_id=game.game_id, models=[model], **check)
                        checks_by_inputs[inputs] = record
                        mc_checks.append(record)
            writer.event(game.game_id, "evaluation_released")
        writer.json("trial_ledger.json", trial_ledger)
        writer.json("evaluation.json", evaluated)
        report = metric_report(
            predictions,
            evaluated,
            final_labels,
            synthetic=source_manifest["synthetic"],
            population_accounting=population_accounting,
            external_population_exclusions=external_exclusions,
        )
        report["monte_carlo"] = {
            "checks": mc_checks,
            "flagged_probabilities": sum(
                v["flagged"] for c in mc_checks for v in c.get("probabilities", {}).values()
            ),
            "flagged_scores": sum(
                v["flagged"] for c in mc_checks for v in c.get("scores", {}).values()
            ),
            "maximum_probability_difference": max(
                (v["difference"] for c in mc_checks for v in c.get("probabilities", {}).values()),
                default=None,
            ),
            "maximum_crps_difference": max(
                (v["difference"] for c in mc_checks for v in c.get("scores", {}).values()),
                default=None,
            ),
        }
        writer.json("metrics.json", report)
        writer.json("exclusions.json", dataset.exclusions)
        writer.json(
            "manifest.json",
            {
                "config": configuration,
                "source_manifest": source_manifest,
                "provenance": provenance(),
                "status": "complete",
                "predictions_hash": hashlib.sha256(
                    (writer.path / "predictions.jsonl").read_bytes()
                ).hexdigest(),
                "splits_hash": digest(splits),
                "selections": {str(y): s for y, s in selections.items()},
            },
        )
    except BaseException as exc:
        writer.failure(exc)
        raise
    finally:
        writer.close()
    return writer.path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, default=20261008, choices=(20261008,))
    args = parser.parse_args()
    try:
        output = run(args.manifest, run_id=args.run_id, run_seed=args.seed)
    except (ValueError, FileExistsError) as exc:
        parser.exit(2, f"RF-001 refused: {exc}\n")
    print(output)


if __name__ == "__main__":
    main()
