"""Deterministic research-only auxiliary regression baselines.

These models deliberately fail closed.  They never impute missing targets or
features and never emit a prediction before a minimum causal training sample
has been observed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class AuxiliaryPrediction:
    value: float | None
    status: str
    reason: str | None
    observations: int


def _valid_row(row: Sequence[float], width: int) -> bool:
    return len(row) == width and all(math.isfinite(float(v)) for v in row)


def fit_predict_ridge(
    train_features: Sequence[Sequence[float]],
    train_targets: Sequence[float | None],
    predict_features: Sequence[float],
    *,
    min_observations: int = 20,
    l2: float = 1e-6,
) -> AuxiliaryPrediction:
    """Fit a tiny deterministic ridge model and predict one strictly-later row."""
    if min_observations < 2 or not math.isfinite(l2) or l2 < 0:
        return AuxiliaryPrediction(None, "NO_TRADE", "invalid_configuration", 0)
    width = len(predict_features)
    if width == 0 or not _valid_row(predict_features, width):
        return AuxiliaryPrediction(None, "NO_TRADE", "invalid_prediction_features", 0)
    if len(train_features) != len(train_targets):
        return AuxiliaryPrediction(None, "NO_TRADE", "feature_target_length_mismatch", 0)

    rows: list[list[float]] = []
    targets: list[float] = []
    for row, target in zip(train_features, train_targets):
        if target is None or not math.isfinite(float(target)) or not _valid_row(row, width):
            continue
        rows.append([1.0, *[float(v) for v in row]])
        targets.append(float(target))

    n = len(rows)
    if n < min_observations:
        return AuxiliaryPrediction(None, "NO_TRADE", "insufficient_training_data", n)

    size = width + 1
    gram = [[0.0] * size for _ in range(size)]
    rhs = [0.0] * size
    for row, target in zip(rows, targets):
        for i in range(size):
            rhs[i] += row[i] * target
            for j in range(size):
                gram[i][j] += row[i] * row[j]
    for i in range(1, size):
        gram[i][i] += l2

    # Deterministic Gaussian elimination with partial pivoting.
    aug = [gram[i] + [rhs[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) <= 1e-12:
            return AuxiliaryPrediction(None, "NO_TRADE", "singular_training_matrix", n)
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [v / scale for v in aug[col]]
        for row_idx in range(size):
            if row_idx == col:
                continue
            factor = aug[row_idx][col]
            aug[row_idx] = [a - factor * b for a, b in zip(aug[row_idx], aug[col])]

    weights = [aug[i][-1] for i in range(size)]
    vector = [1.0, *[float(v) for v in predict_features]]
    value = sum(w * x for w, x in zip(weights, vector))
    if not math.isfinite(value):
        return AuxiliaryPrediction(None, "NO_TRADE", "non_finite_prediction", n)
    return AuxiliaryPrediction(value, "OK", None, n)
