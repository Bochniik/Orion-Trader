"""Leakage-safe stacked multi-task directional baseline.

The stacker consumes only OOF auxiliary predictions.  Rows without both
auxiliary predictions remain unavailable; no target or feature is imputed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from app.services.auxiliary_models import fit_predict_ridge
from app.services.auxiliary_oof import OOFRow


@dataclass(frozen=True)
class StackedPrediction:
    index: int
    score: float | None
    status: str
    reason: str | None
    training_end_index: int | None


def expanding_oof_stacked_directional_predictions(
    base_features: Sequence[Sequence[float]],
    direction_targets: Sequence[float | None],
    auxiliary_oof: Sequence[OOFRow],
    *,
    min_observations: int = 20,
    l2: float = 1e-6,
) -> list[StackedPrediction]:
    """Predict row i from rows < i using base + already-OOF auxiliary features."""
    n = len(base_features)
    if n != len(direction_targets) or n != len(auxiliary_oof):
        return [StackedPrediction(i, None, "NO_TRADE", "length_mismatch", None) for i in range(n)]

    stacked: list[list[float] | None] = []
    for i, (features, aux) in enumerate(zip(base_features, auxiliary_oof)):
        if aux.index != i or aux.status != "OK" or aux.volatility is None or aux.volume is None:
            stacked.append(None)
            continue
        values = [*map(float, features), float(aux.volatility), float(aux.volume)]
        stacked.append(values if values and all(math.isfinite(v) for v in values) else None)

    out: list[StackedPrediction] = []
    for i in range(n):
        current = stacked[i]
        if current is None:
            out.append(StackedPrediction(i, None, "NO_TRADE", "auxiliary_oof_unavailable", None))
            continue
        train_x: list[list[float]] = []
        train_y: list[float | None] = []
        training_end: int | None = None
        for j in range(i):
            if stacked[j] is None:
                continue
            train_x.append(stacked[j])
            train_y.append(direction_targets[j])
            training_end = j
        prediction = fit_predict_ridge(
            train_x,
            train_y,
            current,
            min_observations=min_observations,
            l2=l2,
        )
        if prediction.status != "OK":
            out.append(StackedPrediction(i, None, "NO_TRADE", prediction.reason, training_end))
        else:
            out.append(StackedPrediction(i, prediction.value, "OK", None, training_end))
    return out
