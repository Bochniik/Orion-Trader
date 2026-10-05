from __future__ import annotations

import hashlib
import json
import os
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from app.services.premarket_predictive_engine import FEATURE_NAMES, extract_predictive_features

MODEL_VERSION = "premarket_directional_v5_hybrid_return"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "premarket_directional_v5_hybrid_return.json"
DEFAULT_PROVENANCE_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "premarket_directional_v5_hybrid_return.provenance.json"
PREMARKET_TARGETS = ("premarket_5m", "premarket_15m", "premarket_30m")
RESEARCH_NORMALIZED_MOVE_THRESHOLD = 0.20
RESEARCH_DIRECTION_CONFIDENCE_THRESHOLD = 0.55
V5_EXTRA_FEATURES = (
    "minutes_to_open_scaled", "is_early", "is_mid", "is_late",
    "abs_gap_pct", "abs_vwap_distance_pct", "abs_session_return_pct", "abs_trend_slope",
    "momentum_5_15_agreement", "momentum_15_30_agreement", "gap_momentum_alignment",
    "vwap_momentum_alignment", "trend_volume_interaction", "trend_volatility_interaction",
    "range_volume_interaction", "volatility_ratio_15_30", "coverage_quality", "freshness_quality",
)
V5_FEATURE_NAMES = tuple(FEATURE_NAMES) + V5_EXTRA_FEATURES


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _sigmoid(value: float) -> float:
    return float(1.0 / (1.0 + np.exp(-float(np.clip(value, -50.0, 50.0)))))


def _regime(minutes_to_open: float) -> str:
    if minutes_to_open > 165:
        return "early"
    if minutes_to_open > 30:
        return "mid"
    return "late"


def _sign(value: float) -> float:
    if not np.isfinite(value) or value == 0:
        return 0.0
    return 1.0 if value > 0 else -1.0


def _engineer(features: Dict[str, Any], *, minutes_to_open: float) -> Dict[str, float]:
    base = {
        name: np.nan if _finite(features.get(name)) is None else float(features.get(name))
        for name in FEATURE_NAMES
    }
    regime = _regime(float(minutes_to_open))
    gap, r5, r15, r30 = (base["gap_pct"], base["return_5m_pct"], base["return_15m_pct"], base["return_30m_pct"])
    session_ret = base["session_return_pct"]
    vwap = base["vwap_distance_pct"]
    trend = base["trend_slope_pct_per_minute"]
    rv15, rv30 = base["realized_volatility_15m"], base["realized_volatility_30m"]
    vol_acc = base["volume_acceleration_30m"]
    range_width = base["range_width_pct"]
    cov30, cov60 = base["bar_coverage_30m"], base["bar_coverage_60m"]
    age = base["last_bar_age_minutes"]

    def agreement(a: float, b: float) -> float:
        return np.nan if not np.isfinite(a) or not np.isfinite(b) else _sign(a) * _sign(b)

    def alignment(a: float, b: float) -> float:
        return np.nan if not np.isfinite(a) or not np.isfinite(b) else _sign(a) * b

    extras = {
        "minutes_to_open_scaled": float(np.clip(minutes_to_open / 330.0, 0.0, 1.0)),
        "is_early": 1.0 if regime == "early" else 0.0,
        "is_mid": 1.0 if regime == "mid" else 0.0,
        "is_late": 1.0 if regime == "late" else 0.0,
        "abs_gap_pct": abs(gap) if np.isfinite(gap) else np.nan,
        "abs_vwap_distance_pct": abs(vwap) if np.isfinite(vwap) else np.nan,
        "abs_session_return_pct": abs(session_ret) if np.isfinite(session_ret) else np.nan,
        "abs_trend_slope": abs(trend) if np.isfinite(trend) else np.nan,
        "momentum_5_15_agreement": agreement(r5, r15),
        "momentum_15_30_agreement": agreement(r15, r30),
        "gap_momentum_alignment": alignment(gap, r15),
        "vwap_momentum_alignment": alignment(vwap, r15),
        "trend_volume_interaction": trend * np.log1p(max(vol_acc, 0.0)) if np.isfinite(trend) and np.isfinite(vol_acc) else np.nan,
        "trend_volatility_interaction": trend / (abs(rv30) + 0.05) if np.isfinite(trend) and np.isfinite(rv30) else np.nan,
        "range_volume_interaction": range_width * np.log1p(max(vol_acc, 0.0)) if np.isfinite(range_width) and np.isfinite(vol_acc) else np.nan,
        "volatility_ratio_15_30": rv15 / (abs(rv30) + 1e-6) if np.isfinite(rv15) and np.isfinite(rv30) else np.nan,
        "coverage_quality": min(cov30, cov60) if np.isfinite(cov30) and np.isfinite(cov60) else np.nan,
        "freshness_quality": 1.0 / (1.0 + max(age, 0.0)) if np.isfinite(age) else np.nan,
    }
    return {**base, **extras}


def _minutes_to_open(as_of: Any) -> Optional[float]:
    try:
        stamp = pd.Timestamp(as_of)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        local = stamp.tz_convert("America/New_York")
    except Exception:
        return None
    value = (9 * 60 + 30) - (local.hour * 60 + local.minute + local.second / 60.0)
    return float(value) if value >= 0 else None


def _sigma_pct(features: Dict[str, Any], horizon_minutes: int) -> Optional[float]:
    rv = _finite(features.get("realized_volatility_30m"))
    if rv is None:
        rv = _finite(features.get("realized_volatility_15m"))
    if rv is None or rv <= 0:
        return None
    return float(rv * sqrt(float(horizon_minutes)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_artifact(model_path: Optional[str | Path] = None) -> tuple[Optional[dict], Optional[str], Path]:
    configured = model_path or os.getenv("ORION_PREMARKET_V5_MODEL_PATH") or DEFAULT_MODEL_PATH
    path = Path(configured)
    if not path.exists():
        return None, "premarket_v5_model_artifact_missing", path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"premarket_v5_model_invalid:{type(exc).__name__}", path
    if payload.get("model_version") != MODEL_VERSION:
        return None, "premarket_v5_model_version_mismatch", path
    if tuple(payload.get("feature_names") or ()) != V5_FEATURE_NAMES:
        return None, "premarket_v5_feature_schema_mismatch", path
    targets = payload.get("targets") or {}
    if any(target not in targets for target in PREMARKET_TARGETS):
        return None, "premarket_v5_targets_missing", path
    return payload, None, path


def _predict_target(engineered: Dict[str, float], payload: dict) -> tuple[float, float, int]:
    names = tuple(payload.get("feature_names") or ())
    if names != V5_FEATURE_NAMES:
        raise ValueError("target_feature_schema_mismatch")
    raw = np.asarray([engineered.get(name, np.nan) for name in names], dtype=float)
    missing = int(np.isnan(raw).sum())
    impute = np.asarray(payload["impute"], dtype=float)
    mean = np.asarray(payload["mean"], dtype=float)
    scale = np.asarray(payload["scale"], dtype=float)
    if any(array.shape != raw.shape for array in (impute, mean, scale)):
        raise ValueError("invalid_v5_scaler_dimensions")
    scale = np.where(np.abs(scale) < 1e-12, 1.0, scale)
    x = (np.where(np.isnan(raw), impute, raw) - mean) / scale
    return_stage = payload["return_stage"]
    direction_stage = payload["direction_stage"]
    predicted_return = float(x @ np.asarray(return_stage["weights"], dtype=float) + float(return_stage["bias"]))
    logit = (float(x @ np.asarray(direction_stage["weights"], dtype=float)) + float(direction_stage["bias"])) / float(direction_stage["temperature"])
    return predicted_return, _sigmoid(logit), missing


def predict_premarket_v5_outlook(
    minute_frame: Any,
    *,
    previous_close: Any,
    feed: str,
    as_of: Any = None,
    model_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Causal short-horizon premarket research forecast.

    The deployed V5 artifact was trained on consolidated SIP history. It is
    deliberately research-only: a passing research gate is not promoted to an
    execution/actionable signal, and these targets are never relabelled as
    post-open forecasts.
    """
    if str(feed or "").lower() != "sip":
        return {
            "available": False,
            "actionable": False,
            "research_only": True,
            "forecast_scope": "premarket_short_horizon",
            "model_version": MODEL_VERSION,
            "reason": "training_feed_mismatch_requires_sip",
            "signals": {},
        }
    if not isinstance(minute_frame, pd.DataFrame) or minute_frame.empty:
        return {
            "available": False,
            "actionable": False,
            "research_only": True,
            "forecast_scope": "premarket_short_horizon",
            "model_version": MODEL_VERSION,
            "reason": "usable_sip_minute_history_required",
            "signals": {},
        }

    cutoff = as_of if as_of is not None else minute_frame.index[-1]
    features = extract_predictive_features(minute_frame, previous_close=previous_close, as_of=cutoff)
    minutes = _minutes_to_open(cutoff)
    if minutes is None:
        return {
            "available": False,
            "actionable": False,
            "research_only": True,
            "forecast_scope": "premarket_short_horizon",
            "model_version": MODEL_VERSION,
            "reason": "invalid_premarket_as_of",
            "signals": {},
            "features": features,
        }

    artifact, error, resolved_path = _load_artifact(model_path)
    if error:
        return {
            "available": False,
            "actionable": False,
            "research_only": True,
            "forecast_scope": "premarket_short_horizon",
            "model_version": MODEL_VERSION,
            "reason": error,
            "signals": {},
            "features": features,
            "model_path": str(resolved_path),
        }

    engineered = _engineer(features, minutes_to_open=minutes)
    signals: Dict[str, Any] = {}
    for target in PREMARKET_TARGETS:
        horizon = int(target.removeprefix("premarket_").removesuffix("m"))
        target_payload = artifact["targets"][target]
        predicted_return, p_up, missing = _predict_target(engineered, target_payload)
        confidence = max(p_up, 1.0 - p_up)
        sigma = _sigma_pct(features, horizon)
        normalized_move = abs(predicted_return) / sigma if sigma else None
        regression_up = predicted_return > 0
        classifier_up = p_up >= 0.5
        agreement = regression_up == classifier_up
        research_gate = bool(
            agreement
            and normalized_move is not None
            and normalized_move >= RESEARCH_NORMALIZED_MOVE_THRESHOLD
            and confidence >= RESEARCH_DIRECTION_CONFIDENCE_THRESHOLD
        )
        raw_direction = "UP" if regression_up else "DOWN"
        signals[target] = {
            "target": target,
            "window_label": f"NEXT {horizon} MIN (PREMARKET)",
            "forecast_scope": "premarket_short_horizon",
            "research_only": True,
            "actionable": False,
            "research_gate_passed": research_gate,
            "direction": raw_direction if research_gate else "NO_TRADE",
            "raw_direction": raw_direction,
            "predicted_return_pct": round(predicted_return, 6),
            "probability_up": round(p_up, 6),
            "probability_down": round(1.0 - p_up, 6),
            "direction_confidence": round(confidence, 6),
            "expected_sigma_pct": None if sigma is None else round(sigma, 6),
            "normalized_predicted_move": None if normalized_move is None else round(normalized_move, 6),
            "model_agreement": bool(agreement),
            "imputed_feature_count": missing,
            "gate": {
                "normalized_move_threshold": RESEARCH_NORMALIZED_MOVE_THRESHOLD,
                "direction_threshold": RESEARCH_DIRECTION_CONFIDENCE_THRESHOLD,
            },
            "test_metrics": target_payload.get("test_metrics"),
            "reason": None if research_gate else "below_research_gate",
        }

    provenance = None
    if DEFAULT_PROVENANCE_PATH.exists() and resolved_path.resolve() == DEFAULT_MODEL_PATH.resolve():
        try:
            provenance = json.loads(DEFAULT_PROVENANCE_PATH.read_text(encoding="utf-8"))
        except Exception:
            provenance = None

    return {
        "available": True,
        "actionable": False,
        "research_only": True,
        "forecast_scope": "premarket_short_horizon",
        "model_version": MODEL_VERSION,
        "reason": "research_forecast_available",
        "signals": signals,
        "features": features,
        "minutes_to_open": round(minutes, 3),
        "model_artifact_sha256": _sha256(resolved_path),
        "metadata": artifact.get("metadata") or {},
        "provenance": provenance,
    }
