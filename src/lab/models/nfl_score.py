"""RF-001 weighted score regression and paired integer-score approximation.

This is neither a scoring-play simulator nor a guarantee of feasible score pairs.
NumPy is already pinned by the project's scientific dependencies in uv.lock.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from lab.backtest.score_artifacts import observation_root
from lab.backtest.score_data import FINISH_LAG, digest, stamp, utc


class FitUnavailable(RuntimeError):
    """Expected numerical fitting failure; unexpected exceptions are not swallowed."""


class DistributionUnavailable(RuntimeError):
    """No usable residuals / unable to retain enough non-tied postseason draws."""


@dataclass(frozen=True)
class ScoreFit:
    intercept: float
    home_bonus: float
    offense: dict[str, float]
    defense: dict[str, float]
    audit: dict

    def predict(self, home, away, neutral=False):
        return tuple(
            max(0.0, x)
            for x in (
                self.intercept
                + self.offense.get(home, 0)
                + self.defense.get(away, 0)
                + (0 if neutral else self.home_bonus),
                self.intercept + self.offense.get(away, 0) + self.defense.get(home, 0),
            )
        )


def fit_score(observations, as_of: datetime, penalty=0.001, half_life=None, *, league=False):
    as_of = utc(as_of)
    observations = sorted(observations, key=lambda o: (o.game.kickoff, o.game.game_id))
    if not observations or any(o.game.kickoff + FINISH_LAG >= as_of for o in observations):
        raise ValueError("nonempty eligible history required")
    if penalty <= 0 or not np.isfinite(penalty) or (half_life is not None and half_life <= 0):
        raise ValueError("invalid penalty/half_life")
    if league:
        half_life = None
    teams = (
        []
        if league
        else sorted({t for o in observations for t in (o.game.home_team, o.game.away_team)})
    )
    indices = {t: i for i, t in enumerate(teams)}
    has_home = any(o.game.location != "Neutral" for o in observations)
    unpenalized = 2 if has_home else 1
    size = unpenalized + 2 * len(teams)
    x, y, weights = [], [], []
    for obs in observations:
        game = obs.game
        age = (as_of - game.kickoff).total_seconds() / 86400
        weight = 1 if half_life is None else 2 ** (-age / half_life)
        for team, opponent, score, home in (
            (game.home_team, game.away_team, obs.label.home_score, game.location != "Neutral"),
            (game.away_team, game.home_team, obs.label.away_score, False),
        ):
            row = np.zeros(size)
            row[0] = 1
            if has_home:
                row[1] = int(home)
            if teams:
                row[unpenalized + indices[team]] = 1
                row[unpenalized + len(teams) + indices[opponent]] = 1
            x.append(row)
            y.append(score)
            weights.append(weight)
    weights = np.asarray(weights)
    if not np.isfinite(weights).all() or weights.sum() <= 0:
        raise FitUnavailable("invalid/underflowed training weights")
    # Normalize the data loss; append only penalized effect rows. This gives
    # exactly the specified mean-weighted objective, with no intercept penalty.
    scale = np.sqrt(weights / weights.sum())
    design = np.asarray(x) * scale[:, None]
    target = np.asarray(y, dtype=float) * scale
    if teams:
        regularizer = np.zeros((2 * len(teams), size))
        regularizer[:, unpenalized:] = np.eye(2 * len(teams)) * np.sqrt(penalty)
        design = np.vstack([design, regularizer])
        target = np.concatenate([target, np.zeros(2 * len(teams))])
    try:
        beta = np.linalg.lstsq(design, target, rcond=None)[0]
    except np.linalg.LinAlgError as exc:
        raise FitUnavailable("score least-squares failure") from exc
    if not np.isfinite(beta).all():
        raise FitUnavailable("nonfinite score coefficients")
    audit = {
        "as_of": stamp(as_of),
        "n_games": len(observations),
        "penalty": None if league else penalty,
        "half_life": half_life,
        "league": league,
        "teams": teams,
        "training_root": observation_root(observations),
    }
    audit["input_hash"] = digest(audit)
    audit["coefficients"] = beta.tolist()
    return ScoreFit(
        float(beta[0]),
        float(beta[1]) if has_home else 0.0,
        {t: float(beta[unpenalized + i]) for t, i in indices.items()},
        {t: float(beta[unpenalized + len(teams) + i]) for t, i in indices.items()},
        audit,
    )


def stable_seed(run_seed, game_id, as_of, namespace="distribution-v1"):
    value = f"{int(run_seed)}|{game_id}|{stamp(as_of)}|{namespace}"
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


@dataclass(frozen=True)
class ScoreDistribution:
    samples: np.ndarray
    bank: list[dict]
    seed: int
    rejected: int
    attempts: int
    summary: dict


def sample_scores(means, bank, game_id, as_of, run_seed, game_type, *, n_draws=10000):
    if not bank:
        raise DistributionUnavailable("empty chronological residual bank")
    bank = sorted(bank, key=lambda r: (utc(r["kickoff"]), r["game_id"]))
    if len({r["game_id"] for r in bank}) != len(bank):
        raise ValueError("duplicate residual game")
    residuals = np.asarray([r["residual"] for r in bank], dtype=float)
    if residuals.shape != (len(bank), 2) or not np.isfinite(residuals).all():
        raise ValueError("invalid paired residuals")
    if not np.isfinite(means).all() or n_draws < 1:
        raise ValueError("invalid means/draw count")
    residual_center = residuals.mean(axis=0)
    residuals = residuals - residual_center
    seed = stable_seed(run_seed, game_id, as_of)
    rng = np.random.Generator(np.random.PCG64(seed))
    batches, retained, attempts, rejected = [], 0, 0, 0
    while retained < n_draws and attempts < 1000000:
        count = min(n_draws - retained, 1000000 - attempts)
        indices = rng.integers(0, len(bank), size=count)
        draws = np.maximum(0, np.floor(np.asarray(means) + residuals[indices] + 0.5)).astype(
            np.int64
        )
        attempts += count
        if game_type != "REG":
            valid = draws[:, 0] != draws[:, 1]
            rejected += int((~valid).sum())
            draws = draws[valid]
        batches.append(draws)
        retained += len(draws)
    if retained < n_draws:
        raise DistributionUnavailable("insufficient non-tied postseason pairs within attempt cap")
    samples = np.concatenate(batches)
    home, away = samples.T
    margin, total = home - away, home + away
    p_home, p_away, p_tie = (
        float(np.mean(margin > 0)),
        float(np.mean(margin < 0)),
        float(np.mean(margin == 0)),
    )
    summary = {
        "p_home": p_home,
        "p_away": p_away,
        "p_tie": p_tie,
        "p_share": p_home + 0.5 * p_tie,
        "expected_home_points": float(home.mean()),
        "expected_away_points": float(away.mean()),
        "expected_margin": float(margin.mean()),
        "expected_total": float(total.mean()),
        "fitted_home_mean": float(means[0]),
        "fitted_away_mean": float(means[1]),
        "residual_center": residual_center.tolist(),
        "score_one_draws": int(np.any(samples == 1, axis=1).sum()),
        "one_below_six_opponent_draws": int(
            ((home == 1) & (away < 6) | (away == 1) & (home < 6)).sum()
        ),
    }
    for name, values in (("home", home), ("away", away), ("margin", margin), ("total", total)):
        for level, q in ((50, 0.25), (80, 0.1), (95, 0.025)):
            lo, hi = np.quantile(values, [q, 1 - q], method="inverted_cdf")
            summary[f"{name}_{level}_interval"] = [int(lo), int(hi)]
    return ScoreDistribution(samples, bank, seed, rejected, attempts, summary)
