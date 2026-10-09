"""Saved-forecast scoring and paired chronological inference for RF-001."""

from __future__ import annotations

import math

import numpy as np


def crps(samples, observed):
    x = np.sort(np.asarray(samples, dtype=float))
    if not len(x) or not np.isfinite(x).all() or not np.isfinite(observed):
        raise ValueError("finite nonempty samples/label required")
    # Half the ordered-pair mean absolute difference, including diagonal zeros.
    half_pair = np.dot(2 * np.arange(1, len(x) + 1) - len(x) - 1, x) / len(x) ** 2
    return float(np.abs(x - observed).mean() - half_pair)


def probability_losses(p, y):
    if not 0 <= p <= 1 or y not in (0, 0.5, 1):
        raise ValueError("invalid home-result share/label")
    clipped = float(np.clip(p, 1e-6, 1 - 1e-6))
    return {
        "brier": (p - y) ** 2,
        "log_loss": -y * math.log(clipped) - (1 - y) * math.log(1 - clipped),
        "clipped": int(clipped != p),
        "unclipped_p": p,
    }


def score_draws(samples, observed, energy_seed):
    samples = np.asarray(samples)
    home, away = samples.T
    margin, total = home - away, home + away
    hs, aws = observed
    y = 1 if hs > aws else 0 if hs < aws else 0.5
    probs = np.array([np.mean(margin > 0), np.mean(margin < 0), np.mean(margin == 0)])
    outcome = 0 if hs > aws else 1 if hs < aws else 2
    result = probability_losses(float(probs[0] + 0.5 * probs[2]), y)
    result.update(
        margin_crps=crps(margin, hs - aws),
        total_crps=crps(total, hs + aws),
        three_way_brier=float(np.sum((probs - np.eye(3)[outcome]) ** 2)),
        three_way_log_loss=-math.log(max(1e-6, float(probs[outcome]))),
        three_way_clipped=int(probs[outcome] < 1e-6),
        exact_score_mass=float(np.mean(np.all(samples == observed, axis=1))),
        energy_seed=int(energy_seed),
    )
    first = float(np.linalg.norm(samples - np.asarray(observed), axis=1).mean())
    for suffix, seed in (("", energy_seed), ("_repeat", energy_seed + 1)):
        rng = np.random.Generator(np.random.PCG64(seed))
        indices = rng.integers(0, len(samples), size=(10000, 2))
        second = np.linalg.norm(samples[indices[:, 0]] - samples[indices[:, 1]], axis=1).mean()
        result[f"energy{suffix}"] = float(first - 0.5 * second)
    result["energy_sensitivity"] = abs(result["energy"] - result["energy_repeat"])
    pit_rng = np.random.Generator(np.random.PCG64(energy_seed + 2))
    result["pit_seed"] = int(energy_seed + 2)
    for name, values, label in (
        ("home", home, hs),
        ("away", away, aws),
        ("margin", margin, hs - aws),
        ("total", total, hs + aws),
    ):
        bias = float(values.mean() - label)
        result[f"{name}_bias"] = bias
        result[f"{name}_mae"] = abs(bias)
        result[f"{name}_squared_error"] = bias**2
        result[f"{name}_pit"] = float(
            np.mean(values < label) + pit_rng.random() * np.mean(values == label)
        )
        for level, q in ((50, 0.25), (80, 0.1), (95, 0.025)):
            lo, hi = np.quantile(values, [q, 1 - q], method="inverted_cdf")
            result[f"{name}_{level}_covered"] = int(lo <= label <= hi)
            result[f"{name}_{level}_width"] = float(hi - lo)
    return result


def select_setting(trials, outer_season):
    ledger, available = [], []
    for trial in trials:
        losses = [x for x in trial["losses"] if 2012 <= x["season"] < outer_season]
        row = {
            "penalty": trial["penalty"],
            "half_life": trial["half_life"],
            "outer_season": outer_season,
            "n": len(losses),
            "status": "scored" if losses else "unavailable",
            "margin_crps": float(np.mean([x["margin_crps"] for x in losses])) if losses else None,
            "by_year": {
                str(year): float(np.mean([x["margin_crps"] for x in losses if x["season"] == year]))
                for year in sorted({x["season"] for x in losses})
            },
        }
        ledger.append(row)
        if losses:
            available.append(row)
    if not available:
        return None, ledger
    best = min(x["margin_crps"] for x in available)
    ties = [x for x in available if x["margin_crps"] <= best + 0.001]
    chosen = max(ties, key=lambda x: (x["penalty"], x["half_life"] is None, x["half_life"] or 0))
    return (chosen["penalty"], chosen["half_life"]), ledger


def paired_bootstrap(rows, *, replicates=5000, seed=20261008):
    if not rows:
        return {
            "n": 0,
            "mean": None,
            "ci95": None,
            "one_week_ci95": None,
            "season_ci95": None,
            "week_count": 0,
            "seed": seed,
            "replicates": replicates,
        }
    rows = sorted(
        rows, key=lambda x: (x["season"], x["game_type"] != "REG", x["kickoff"], x["game_id"])
    )
    seasons = sorted({r["season"] for r in rows})
    weekly = []
    for season in seasons:
        groups = {}
        for row in rows:
            if row["season"] == season:
                groups.setdefault((row["game_type"], row["week"]), []).append(row)
        ordered = sorted(
            groups, key=lambda key: (key[0] != "REG", min(r["kickoff"] for r in groups[key]))
        )
        weekly.append(
            np.asarray(
                [[sum(r["difference"] for r in groups[k]), len(groups[k])] for k in ordered],
                dtype=float,
            )
        )

    def interval(block, rng):
        losses = []
        for _ in range(replicates):
            sums = np.zeros(2)
            for weeks in weekly:
                length = len(weeks)
                size = min(block, length)
                starts = rng.integers(0, length - size + 1, size=math.ceil(length / size))
                indices = np.concatenate([np.arange(s, s + size) for s in starts])[:length]
                sums += weeks[indices].sum(axis=0)
            losses.append(sums[0] / sums[1])
        return np.quantile(losses, [0.025, 0.975], method="linear").tolist()

    rng = np.random.Generator(np.random.PCG64(seed))
    main = interval(4, rng)
    one = interval(1, rng)
    season_totals = np.asarray([w.sum(axis=0) for w in weekly])
    indices = rng.integers(0, len(seasons), size=(replicates, len(seasons)))
    totals = season_totals[indices].sum(axis=1)
    season_ci = np.quantile(totals[:, 0] / totals[:, 1], [0.025, 0.975], method="linear").tolist()
    return {
        "n": len(rows),
        "mean": float(np.mean([r["difference"] for r in rows])),
        "ci95": main,
        "one_week_ci95": one,
        "season_ci95": season_ci,
        "week_count": sum(len(w) for w in weekly),
        "seed": seed,
        "replicates": replicates,
    }
