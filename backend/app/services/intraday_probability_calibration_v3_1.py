
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

HORIZONS = ("30m", "1h", "3h", "5h")

# Conservative prior reliability by horizon based on current multi-ticker V3 evidence.
# 1h/3h are treated as primary; 30m/5h are down-weighted until broader validation.
HORIZON_RELIABILITY_PRIOR = {
    "30m": 0.45,
    "1h": 0.80,
    "3h": 0.75,
    "5h": 0.40,
}

# Caps are deliberately conservative.
MAX_DISTANCE_FROM_50 = {
    "30m": 10.0,   # 40-60
    "1h": 15.0,    # 35-65
    "3h": 15.0,
    "5h": 10.0,
}

MIN_DIRECTIONAL_CALLS_FOR_TRUST = 40
MIN_CONFIDENT_CALLS_FOR_TRUST = 20


def _safe_float(value: Any) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if np.isfinite(x) else None


def _clip_probability(p: float, horizon: str) -> float:
    cap = MAX_DISTANCE_FROM_50[horizon]
    return float(np.clip(p, 50.0 - cap, 50.0 + cap))


def _quality_from_metrics(metrics: Dict[str, Any], horizon: str) -> Dict[str, Any]:
    """Convert walk-forward metrics into a conservative 0-100 reliability score."""

    directional_accuracy = _safe_float(metrics.get("directional_accuracy_pct"))
    brier = _safe_float(metrics.get("brier_score"))
    ece = _safe_float(metrics.get("expected_calibration_error_pct"))
    directional_count = int(metrics.get("directional_prediction_count") or 0)

    conf60 = metrics.get("confident_60") or {}
    conf65 = metrics.get("confident_65") or {}
    conf60_acc = _safe_float(conf60.get("accuracy_pct"))
    conf65_acc = _safe_float(conf65.get("accuracy_pct"))
    conf60_count = int(conf60.get("count") or 0)
    conf65_count = int(conf65.get("count") or 0)

    prior = HORIZON_RELIABILITY_PRIOR[horizon]

    score = 50.0

    if directional_accuracy is not None:
        score += (directional_accuracy - 50.0) * 2.2

    if brier is not None:
        score += (0.25 - brier) * 450.0

    if ece is not None:
        score += max(-15.0, min(15.0, (5.0 - ece) * 1.5))

    if directional_count < MIN_DIRECTIONAL_CALLS_FOR_TRUST:
        score -= 8.0

    if conf60_acc is not None and conf60_count >= MIN_CONFIDENT_CALLS_FOR_TRUST:
        score += (conf60_acc - 50.0) * 0.45

    if conf65_acc is not None and conf65_count >= MIN_CONFIDENT_CALLS_FOR_TRUST:
        score += (conf65_acc - 50.0) * 0.35

    score = 50.0 + (score - 50.0) * prior
    score = float(np.clip(score, 0.0, 100.0))

    if score >= 70:
        label = "trusted"
    elif score >= 55:
        label = "usable"
    elif score >= 40:
        label = "caution"
    else:
        label = "low_reliability"

    return {
        "reliability_score": round(score, 1),
        "reliability_label": label,
        "directional_accuracy_pct": directional_accuracy,
        "brier_score": brier,
        "expected_calibration_error_pct": ece,
        "directional_prediction_count": directional_count,
        "confident_60_count": conf60_count,
        "confident_65_count": conf65_count,
    }


def fit_reliability_profile(
    symbol: str,
    backtest_result: Dict[str, Any],
) -> Dict[str, Any]:
    horizons = backtest_result.get("horizons", {})
    profile = {}

    for horizon in HORIZONS:
        metrics = horizons.get(horizon, {})
        if not metrics or not metrics.get("available"):
            profile[horizon] = {
                "available": False,
                "reliability_score": 0.0,
                "reliability_label": "unavailable",
            }
            continue

        profile[horizon] = {
            "available": True,
            **_quality_from_metrics(metrics, horizon),
        }

    return {
        "symbol": symbol.upper(),
        "horizons": profile,
        "method": "walk_forward_reliability_profile_v3_1",
    }


def calibrate_v3_probability(
    horizon: str,
    probability_up: float,
    reliability_score: float,
    *,
    agreement: Optional[str] = None,
) -> Dict[str, Any]:
    p = float(probability_up)
    reliability = float(np.clip(reliability_score, 0.0, 100.0))

    # Map reliability 0-100 -> signal retention 0.15-0.95.
    retention = 0.15 + 0.80 * (reliability / 100.0)

    # Agreement/disagreement modifier.
    if agreement == "directional_agreement":
        retention *= 1.05
    elif agreement == "directional_disagreement":
        retention *= 0.55
    elif agreement in {"neutral_agreement", "partial_agreement"}:
        retention *= 0.80

    retention = float(np.clip(retention, 0.10, 0.98))

    calibrated = 50.0 + (p - 50.0) * retention
    calibrated = _clip_probability(calibrated, horizon)

    if calibrated >= 55.0:
        direction = "bullish"
    elif calibrated <= 45.0:
        direction = "bearish"
    else:
        direction = "neutral"

    if reliability >= 70:
        confidence_label = "high"
    elif reliability >= 55:
        confidence_label = "medium"
    elif reliability >= 40:
        confidence_label = "low"
    else:
        confidence_label = "very_low"

    return {
        "available": True,
        "horizon": horizon,
        "raw_v3_probability_up": round(p, 2),
        "calibrated_probability_up": round(calibrated, 1),
        "calibrated_probability_down": round(100.0 - calibrated, 1),
        "direction": direction,
        "reliability_score": round(reliability, 1),
        "confidence_label": confidence_label,
        "signal_retention": round(retention, 3),
        "confidence_cap_distance_from_50": MAX_DISTANCE_FROM_50[horizon],
        "method": "v3_1_reliability_shrinkage",
    }


def apply_v3_1_filter(
    v3_result: Dict[str, Any],
    reliability_profile: Dict[str, Any],
) -> Dict[str, Any]:
    symbol = str(v3_result.get("symbol") or "").upper()
    output = {
        "symbol": symbol,
        "available": False,
        "horizons": {},
        "method": "v3_1_calibration_filter",
        "semantics": (
            "V3.1 filters V3 probability through horizon/ticker walk-forward reliability. "
            "Low-reliability predictions are shrunk toward 50% instead of being shown as "
            "high-confidence probabilities."
        ),
    }

    profile_horizons = reliability_profile.get("horizons", {})
    v3_horizons = v3_result.get("horizons", {})

    available_any = False

    for horizon in HORIZONS:
        v3_row = v3_horizons.get(horizon, {})
        profile_row = profile_horizons.get(horizon, {})

        if not v3_row.get("available"):
            output["horizons"][horizon] = {
                "available": False,
                "reason": v3_row.get("reason", "V3 unavailable"),
            }
            continue

        reliability = float(profile_row.get("reliability_score") or 0.0)
        calibrated = calibrate_v3_probability(
            horizon,
            float(v3_row["probability_up"]),
            reliability,
            agreement=v3_row.get("agreement"),
        )

        calibrated["v3_direction"] = v3_row.get("direction")
        calibrated["agreement"] = v3_row.get("agreement")
        calibrated["reliability_label"] = profile_row.get("reliability_label")
        calibrated["v1_probability_up"] = v3_row.get("v1_probability_up")
        calibrated["v2_probability_up"] = v3_row.get("v2_probability_up")

        output["horizons"][horizon] = calibrated
        available_any = True

    output["available"] = available_any
    return output


def _self_test() -> Dict[str, Any]:
    fake_backtest = {
        "horizons": {
            "30m": {
                "available": True,
                "directional_accuracy_pct": 50.5,
                "directional_prediction_count": 100,
                "brier_score": 0.251,
                "expected_calibration_error_pct": 4.5,
                "confident_60": {"count": 12, "accuracy_pct": 50.0},
                "confident_65": {"count": 2, "accuracy_pct": 50.0},
            },
            "1h": {
                "available": True,
                "directional_accuracy_pct": 57.0,
                "directional_prediction_count": 140,
                "brier_score": 0.247,
                "expected_calibration_error_pct": 2.0,
                "confident_60": {"count": 30, "accuracy_pct": 60.0},
                "confident_65": {"count": 22, "accuracy_pct": 63.0},
            },
            "3h": {
                "available": True,
                "directional_accuracy_pct": 55.0,
                "directional_prediction_count": 120,
                "brier_score": 0.248,
                "expected_calibration_error_pct": 3.0,
                "confident_60": {"count": 40, "accuracy_pct": 58.0},
                "confident_65": {"count": 20, "accuracy_pct": 60.0},
            },
            "5h": {
                "available": True,
                "directional_accuracy_pct": 49.0,
                "directional_prediction_count": 35,
                "brier_score": 0.255,
                "expected_calibration_error_pct": 8.0,
                "confident_60": {"count": 8, "accuracy_pct": 50.0},
                "confident_65": {"count": 2, "accuracy_pct": 50.0},
            },
        }
    }

    profile = fit_reliability_profile("DEMO", fake_backtest)

    fake_v3 = {
        "symbol": "DEMO",
        "horizons": {
            "30m": {"available": True, "probability_up": 61.0, "direction": "bullish", "agreement": "directional_agreement"},
            "1h": {"available": True, "probability_up": 63.0, "direction": "bullish", "agreement": "directional_agreement"},
            "3h": {"available": True, "probability_up": 40.0, "direction": "bearish", "agreement": "partial_agreement"},
            "5h": {"available": True, "probability_up": 66.0, "direction": "bullish", "agreement": "directional_disagreement"},
        }
    }

    return {
        "self_test": True,
        "reliability_profile": profile,
        "filtered": apply_v3_1_filter(fake_v3, profile),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(_self_test(), indent=2, ensure_ascii=False))
