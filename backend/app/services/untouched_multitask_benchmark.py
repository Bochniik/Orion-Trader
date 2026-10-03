"""Frozen untouched-test comparison for directional research models.

This module only evaluates already-produced predictions. It deliberately does
not fit, calibrate, select thresholds, or otherwise adapt either model using
the untouched test partition.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class UntouchedBenchmark:
    status: str
    reason: str | None
    observations: int
    single_mse: float | None
    multi_mse: float | None
    single_accuracy: float | None
    multi_accuracy: float | None
    mse_delta_multi_minus_single: float | None


def compare_on_untouched_test(
    targets: Sequence[float | None],
    single_predictions: Sequence[float | None],
    multi_predictions: Sequence[float | None],
    *,
    partition_name: str,
    frozen_before_evaluation: bool,
    min_observations: int = 30,
) -> UntouchedBenchmark:
    """Compare frozen predictions on an explicitly named untouched-test split."""
    empty = lambda reason, n=0: UntouchedBenchmark(
        "NO_TRADE", reason, n, None, None, None, None, None
    )
    if partition_name != "untouched_test" or not frozen_before_evaluation:
        return empty("untouched_test_contract_not_satisfied")
    if min_observations < 2:
        return empty("invalid_configuration")
    if not (len(targets) == len(single_predictions) == len(multi_predictions)):
        return empty("length_mismatch")

    rows: list[tuple[float, float, float]] = []
    for target, single, multi in zip(targets, single_predictions, multi_predictions):
        if target is None or single is None or multi is None:
            continue
        values = (float(target), float(single), float(multi))
        if not all(math.isfinite(v) for v in values):
            continue
        if values[0] not in (0.0, 1.0):
            return empty("invalid_direction_target", len(rows))
        rows.append(values)

    n = len(rows)
    if n < min_observations:
        return empty("insufficient_untouched_test_data", n)

    single_mse = sum((s - y) ** 2 for y, s, _ in rows) / n
    multi_mse = sum((m - y) ** 2 for y, _, m in rows) / n
    single_accuracy = sum((s >= 0.5) == bool(y) for y, s, _ in rows) / n
    multi_accuracy = sum((m >= 0.5) == bool(y) for y, _, m in rows) / n
    return UntouchedBenchmark(
        "OK", None, n, single_mse, multi_mse, single_accuracy, multi_accuracy,
        multi_mse - single_mse,
    )
