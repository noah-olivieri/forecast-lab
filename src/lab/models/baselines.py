"""Baselines that need no fitting."""

from __future__ import annotations


def market_mid(bid: float | None, ask: float | None) -> float | None:
    """Mid of a YES quote, or None for a missing or empty book (a 0 bid means no bid)."""
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2
