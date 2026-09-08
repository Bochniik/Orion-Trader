
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from app.services.intraday_probability_ensemble_engine import (
    estimate_intraday_probabilities_v3,
)
from app.services.intraday_probability_calibration_v3_1 import (
    apply_v3_1_filter,
)

# ---------------------------------------------------------------------------
# Prevalidated ticker/horizon reliability profiles
# ---------------------------------------------------------------------------
#
# These values come from the 60d / 5m leakage-safe V3 walk-forward policy
# validation already run for these symbols.
#
# IMPORTANT:
# - They are reliability scores, NOT price probabilities.
# - They must not be silently generalized to every stock.
# - Unknown symbols use a conservative generic prior until a dedicated
#   walk-forward profile is available.
# ---------------------------------------------------------------------------

VALIDATED_RELIABILITY: Dict[str, Dict[str, float]] = {
    "AAPL": {"30m": 51.2, "1h": 72.4, "3h": 29.2, "5h": 42.8},
    "MSFT": {"30m": 52.1, "1h": 63.4, "3h": 53.4, "5h": 45.6},
    "AMD":  {"30m": 50.7, "1h": 56.7, "3h": 48.7, "5h": 43.7},
    "META": {"30m": 46.0, "1h": 25.1, "3h": 69.3, "5h": 49.1},
    "TSLA": {"30m": 56.8, "1h": 61.7, "3h": 72.9, "5h": 56.1},
}

# Conservative fallback. This is intentionally not called "validated".
GENERIC_RELIABILITY_PRIOR: Dict[str, float] = {
    "30m": 48.0,
    "1h": 58.0,
    "3h": 55.0,
    "5h": 44.0,
}


def _label(score: float) -> str:
    if score >= 70.0:
        return "trusted"
    if score >= 55.0:
        return "usable"
    if score >= 40.0:
        return "caution"
    return "low_reliability"


def _policy(score: float) -> str:
    if score >= 70.0:
        return "show_probability"
    if score >= 55.0:
        return "show_probability_with_caution"
    if score >= 40.0:
        return "show_low_confidence_probability"
    return "suppress_directional_probability"


def get_runtime_reliability_profile(symbol: str) -> Dict[str, Any]:
    ticker = str(symbol or "").strip().upper()
    exact = VALIDATED_RELIABILITY.get(ticker)

    if exact is not None:
        scores = exact
        source = "ticker_specific_walk_forward_60d_5m"
        validated = True
    else:
        scores = GENERIC_RELIABILITY_PRIOR
        source = "generic_conservative_prior"
        validated = False

    horizons: Dict[str, Dict[str, Any]] = {}

    for horizon, value in scores.items():
        score = float(value)
        horizons[horizon] = {
            "available": True,
            "reliability_score": round(score, 1),
            "reliability_label": _label(score),
            "display_policy": _policy(score),
            "profile_validated_for_symbol": validated,
        }

    return {
        "symbol": ticker,
        "horizons": horizons,
        "source": source,
        "validated_for_symbol": validated,
        "warning": (
            None
            if validated
            else (
                "No ticker-specific V3.1 walk-forward reliability profile is "
                "stored for this symbol; a conservative generic prior is used."
            )
        ),
    }


def _canonicalize_filtered(
    filtered: Dict[str, Any],
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    result = deepcopy(filtered)
    horizons = result.get("horizons") or {}

    bullish = 0
    bearish = 0

    for horizon, row in horizons.items():
        if not isinstance(row, dict) or not row.get("available"):
            continue

        # Canonical public aliases expected by API/front-end callers.
        row["probability_up"] = row.get("calibrated_probability_up")
        row["probability_down"] = row.get("calibrated_probability_down")

        profile_row = (profile.get("horizons") or {}).get(horizon) or {}
        row["display_policy"] = profile_row.get("display_policy")
        row["profile_validated_for_symbol"] = profile_row.get(
            "profile_validated_for_symbol",
            False,
        )

        direction = str(row.get("direction") or "neutral").lower()
        if direction == "bullish":
            bullish += 1
        elif direction == "bearish":
            bearish += 1

    if bullish > bearish:
        consensus = "bullish"
    elif bearish > bullish:
        consensus = "bearish"
    else:
        consensus = "mixed_or_neutral"

    result["cross_horizon_consensus"] = consensus
    result["reliability_profile_source"] = profile.get("source")
    result["profile_validated_for_symbol"] = profile.get(
        "validated_for_symbol",
        False,
    )
    result["engine_version"] = "V3.1"

    return result


def estimate_intraday_probabilities_v3_1(symbol: str) -> Dict[str, Any]:
    ticker = str(symbol or "").strip().upper()

    raw_v3 = estimate_intraday_probabilities_v3(ticker)
    profile = get_runtime_reliability_profile(ticker)

    filtered = apply_v3_1_filter(
        raw_v3,
        profile,
    )

    filtered = _canonicalize_filtered(
        filtered,
        profile,
    )

    warnings = list(raw_v3.get("warnings") or [])

    profile_warning = profile.get("warning")
    if profile_warning:
        warnings.append(profile_warning)

    # Do not present low-reliability/suppressed horizons as normal predictions.
    for horizon, row in (filtered.get("horizons") or {}).items():
        if not isinstance(row, dict) or not row.get("available"):
            continue

        policy = row.get("display_policy")

        if policy == "suppress_directional_probability":
            row["suppressed_probability_up"] = row.get("probability_up")
            row["suppressed_probability_down"] = row.get("probability_down")
            row["probability_up"] = None
            row["probability_down"] = None
            row["direction"] = "neutral"
            row["confidence_label"] = "very_low"
            row["suppressed"] = True
        else:
            row["suppressed"] = False

    filtered["warnings"] = list(dict.fromkeys(str(w) for w in warnings if w))
    filtered["raw_v3"] = raw_v3
    filtered["reliability_profile"] = profile

    return filtered
