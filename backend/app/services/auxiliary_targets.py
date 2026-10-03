"""Causal auxiliary targets for research-only multi-task models.

Targets require a complete future window. Missing or invalid future
observations fail closed with None; callers must not impute them.
"""
from __future__ import annotations

import math
from typing import Sequence


def future_realized_volatility(prices: Sequence[float], *, anchor: int, horizon: int) -> float | None:
    """RMS log-return volatility strictly after anchor."""
    if horizon < 2 or anchor < 0 or anchor + horizon >= len(prices):
        return None
    window = prices[anchor : anchor + horizon + 1]
    if any(not math.isfinite(float(p)) or float(p) <= 0 for p in window):
        return None
    returns = [math.log(float(window[i]) / float(window[i - 1])) for i in range(1, len(window))]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return math.sqrt(variance)


def future_relative_volume(volumes: Sequence[float], *, anchor: int, horizon: int, baseline_window: int) -> float | None:
    """Future mean volume divided by a strictly historical baseline mean."""
    if horizon < 1 or baseline_window < 1 or anchor < baseline_window - 1:
        return None
    if anchor + horizon >= len(volumes):
        return None
    history = volumes[anchor - baseline_window + 1 : anchor + 1]
    future = volumes[anchor + 1 : anchor + horizon + 1]
    values = [float(v) for v in (*history, *future)]
    if any(not math.isfinite(v) or v < 0 for v in values):
        return None
    baseline = sum(float(v) for v in history) / len(history)
    if baseline <= 0:
        return None
    return (sum(float(v) for v in future) / len(future)) / baseline
