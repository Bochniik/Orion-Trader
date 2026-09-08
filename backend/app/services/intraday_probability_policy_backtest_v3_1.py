
from __future__ import annotations

from typing import Any, Dict

import numpy as np

from app.services.intraday_probability_calibration_v3_1 import (
    fit_reliability_profile,
    calibrate_v3_probability,
)
from app.services.intraday_probability_backtest_v3 import walk_forward_v3


def _recalibrate_horizon_metrics(
    horizon: str,
    base_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Recalibrate summary-level V3 metrics conservatively.

    This module intentionally does NOT fabricate new point-level predictions from
    summary statistics. It reports the reliability profile derived from the
    existing V3 walk-forward output and a recommended production policy.
    """
    if not base_metrics.get("available"):
        return {
            "available": False,
            "reason": "Base V3 horizon unavailable.",
        }

    return {
        "available": True,
        "directional_accuracy_pct": base_metrics.get("directional_accuracy_pct"),
        "directional_prediction_count": base_metrics.get("directional_prediction_count"),
        "brier_score": base_metrics.get("brier_score"),
        "log_loss": base_metrics.get("log_loss"),
        "expected_calibration_error_pct": base_metrics.get("expected_calibration_error_pct"),
        "confident_60": base_metrics.get("confident_60"),
        "confident_65": base_metrics.get("confident_65"),
        "calibration_bins": base_metrics.get("calibration_bins"),
    }


def validate_v3_1_policy(symbol: str) -> Dict[str, Any]:
    base = walk_forward_v3(symbol)
    profile = fit_reliability_profile(symbol, base)

    policy = {}

    for horizon, row in profile.get("horizons", {}).items():
        score = float(row.get("reliability_score") or 0.0)

        if horizon in {"1h", "3h"}:
            role = "primary"
        else:
            role = "secondary"

        if score >= 70:
            display_policy = "show_probability"
        elif score >= 55:
            display_policy = "show_probability_with_caution"
        elif score >= 40:
            display_policy = "show_low_confidence_probability"
        else:
            display_policy = "suppress_directional_probability"

        policy[horizon] = {
            "role": role,
            "reliability_score": score,
            "reliability_label": row.get("reliability_label"),
            "display_policy": display_policy,
            "base_v3_metrics": _recalibrate_horizon_metrics(
                horizon,
                base.get("horizons", {}).get(horizon, {}),
            ),
        }

    return {
        "symbol": symbol.upper(),
        "available": base.get("available", False),
        "base_v3": base,
        "reliability_profile": profile,
        "v3_1_policy": policy,
        "semantics": (
            "V3.1 policy validation. The reliability layer is derived from V3 walk-forward "
            "metrics and determines whether a horizon should be shown normally, shown with "
            "caution, or suppressed. Point-level recalibration is applied at live inference."
        ),
    }


if __name__ == "__main__":
    import json
    import sys

    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "NVDA"
    print(json.dumps(
        validate_v3_1_policy(ticker),
        indent=2,
        ensure_ascii=False,
        default=str,
    ))
