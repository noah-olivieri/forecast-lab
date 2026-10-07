"""538-style NFL Elo: pure math, no I/O. Defaults are FiveThirtyEight's, untuned (v0)."""

from __future__ import annotations

import math

K = 20.0
HFA = 65.0  # Elo points added to the home team's rating (0 at neutral sites)
MEAN_ELO = 1505.0
INIT_ELO = 1500.0
REGRESSION = 1 / 3  # share of the gap to the mean given back between seasons
SCALE = 400.0


def expected_home(elo_home: float, elo_away: float, hfa: float = HFA) -> float:
    """P(home win), including the home-field adjustment."""
    return 1.0 / (1.0 + 10.0 ** (-(elo_home + hfa - elo_away) / SCALE))


def winner_elo_diff(elo_home: float, elo_away: float, hfa: float, home_won: bool) -> float:
    """Winner's pregame Elo minus loser's, signed, home-field adjustment included."""
    diff = (elo_home + hfa) - elo_away
    return diff if home_won else -diff


def mov_multiplier(margin: int, winner_diff: float) -> float:
    """ln(|margin|+1) * 2.2 / (0.001 * winner_diff + 2.2). A tie (margin 0) gives 0."""
    return math.log(abs(margin) + 1) * 2.2 / (0.001 * winner_diff + 2.2)


def update(
    elo_home: float, elo_away: float, home_score: int, away_score: int, hfa: float = HFA
) -> tuple[float, float]:
    """Post-game ratings. Zero-sum. Ties leave ratings unchanged (multiplier is 0)."""
    margin = home_score - away_score
    result = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
    mult = mov_multiplier(margin, winner_elo_diff(elo_home, elo_away, hfa, margin > 0))
    shift = K * mult * (result - expected_home(elo_home, elo_away, hfa))
    return elo_home + shift, elo_away - shift


def regress_to_mean(ratings: dict[str, float]) -> dict[str, float]:
    return {t: r + REGRESSION * (MEAN_ELO - r) for t, r in ratings.items()}
