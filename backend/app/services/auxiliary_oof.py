"""Leakage-safe out-of-fold auxiliary predictions for stacked research models."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from app.services.auxiliary_models import fit_predict_ridge

@dataclass(frozen=True)
class OOFRow:
    index: int
    volatility: float | None
    volume: float | None
    status: str
    reason: str | None
    training_end_index: int | None

def expanding_oof_auxiliary_predictions(features: Sequence[Sequence[float]], volatility_targets: Sequence[float | None], volume_targets: Sequence[float | None], *, min_observations: int = 20, l2: float = 1e-6) -> list[OOFRow]:
    """Predict row i using only rows < i; unavailable evidence stays unavailable."""
    n = len(features)
    if n != len(volatility_targets) or n != len(volume_targets):
        return [OOFRow(i, None, None, "NO_TRADE", "length_mismatch", None) for i in range(n)]
    out: list[OOFRow] = []
    for i in range(n):
        if i == 0:
            out.append(OOFRow(i, None, None, "NO_TRADE", "insufficient_training_data", None))
            continue
        vol = fit_predict_ridge(features[:i], volatility_targets[:i], features[i], min_observations=min_observations, l2=l2)
        volume = fit_predict_ridge(features[:i], volume_targets[:i], features[i], min_observations=min_observations, l2=l2)
        if vol.status != "OK" or volume.status != "OK":
            reasons = sorted({r for r in (vol.reason, volume.reason) if r})
            out.append(OOFRow(i, None, None, "NO_TRADE", "+".join(reasons) if reasons else "auxiliary_prediction_unavailable", i - 1))
        else:
            out.append(OOFRow(i, vol.value, volume.value, "OK", None, i - 1))
    return out
