from __future__ import annotations

import json
import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from app.services.premarket_predictive_engine import FEATURE_NAMES, extract_predictive_features


MODEL_VERSION = "premarket_predictive_v3_hierarchical"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "premarket_predictive_v3_hierarchical.json"

# Only this gate passed the current fold-stability requirements.
ROBUST_GATES = {
    "open_5m": {
        "edge_threshold": 0.55,
        "direction_threshold": 0.55,
        "validation": {
            "samples": 619,
            "coverage": 0.033,
            "aggregate_directional_accuracy": 0.646,
            "median_fold_accuracy": 0.613,
            "positive_folds": 5,
            "evaluable_folds": 5,
            "min_fold_accuracy": 0.509,
        },
    },
}


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _sigmoid(value: float) -> float:
    value = float(np.clip(value, -50.0, 50.0))
    return 1.0 / (1.0 + np.exp(-value))


@dataclass(frozen=True)
class BinaryStage:
    weights: np.ndarray
    bias: float
    temperature: float

    @classmethod
    def from_payload(cls, payload: Dict[str, Any], *, feature_count: int) -> "BinaryStage":
        weights = np.asarray(payload.get("weights"), dtype=float)
        bias = float(payload.get("bias", 0.0))
        temperature = float(payload.get("temperature", 1.0))
        if weights.shape != (feature_count,):
            raise ValueError("invalid_stage_weights")
        if temperature <= 0 or not np.isfinite(temperature):
            raise ValueError("invalid_stage_temperature")
        return cls(weights=weights, bias=bias, temperature=temperature)

    def probability(self, x: np.ndarray) -> float:
        logit = (float(self.weights @ x) + self.bias) / self.temperature
        return float(_sigmoid(logit))


@dataclass(frozen=True)
class HierarchicalTargetModel:
    target: str
    feature_names: tuple[str, ...]
    impute: np.ndarray
    mean: np.ndarray
    scale: np.ndarray
    edge_stage: BinaryStage
    direction_stage: BinaryStage

    @classmethod
    def from_payload(cls, target: str, payload: Dict[str, Any]) -> "HierarchicalTargetModel":
        feature_names = tuple(payload.get("feature_names") or ())
        if feature_names != tuple(FEATURE_NAMES):
            raise ValueError("feature_schema_mismatch")
        n = len(feature_names)
        impute = np.asarray(payload.get("impute"), dtype=float)
        mean = np.asarray(payload.get("mean"), dtype=float)
        scale = np.asarray(payload.get("scale"), dtype=float)
        if impute.shape != (n,) or mean.shape != (n,) or scale.shape != (n,):
            raise ValueError("invalid_scaler_dimensions")
        scale = np.where(np.abs(scale) < 1e-12, 1.0, scale)
        return cls(
            target=target,
            feature_names=feature_names,
            impute=impute,
            mean=mean,
            scale=scale,
            edge_stage=BinaryStage.from_payload(payload.get("edge_stage") or {}, feature_count=n),
            direction_stage=BinaryStage.from_payload(payload.get("direction_stage") or {}, feature_count=n),
        )

    def predict(self, features: Dict[str, Optional[float]]) -> Optional[Dict[str, float]]:
        values = np.asarray([
            np.nan if _finite(features.get(name)) is None else float(features.get(name))
            for name in self.feature_names
        ], dtype=float)
        missing = int(np.isnan(values).sum())
        if missing > max(5, len(values) // 2):
            return None
        values = np.where(np.isnan(values), self.impute, values)
        x = (values - self.mean) / self.scale
        p_edge = self.edge_stage.probability(x)
        p_up_given_edge = self.direction_stage.probability(x)
        p_down_given_edge = 1.0 - p_up_given_edge
        return {
            "edge_probability": p_edge,
            "up_given_edge": p_up_given_edge,
            "down_given_edge": p_down_given_edge,
            "probability_up": p_edge * p_up_given_edge,
            "probability_down": p_edge * p_down_given_edge,
            "probability_no_edge": 1.0 - p_edge,
            "direction_confidence": max(p_up_given_edge, p_down_given_edge),
            "imputed_feature_count": missing,
        }


class HierarchicalRegistry:
    def __init__(self, model_path: Optional[str | Path] = None):
        configured = model_path or os.getenv("ORION_PREMARKET_HIERARCHICAL_MODEL_PATH") or DEFAULT_MODEL_PATH
        self.model_path = Path(configured)
        self.models: Dict[str, HierarchicalTargetModel] = {}
        self.metadata: Dict[str, Any] = {}
        self.error: Optional[str] = None
        self._load()

    def _load(self) -> None:
        if not self.model_path.exists():
            self.error = "trained_hierarchical_model_artifact_missing"
            return
        try:
            payload = json.loads(self.model_path.read_text(encoding="utf-8"))
            if payload.get("model_version") != MODEL_VERSION:
                raise ValueError("unsupported_model_version")
            self.metadata = dict(payload.get("metadata") or {})
            for target, model_payload in (payload.get("targets") or {}).items():
                self.models[target] = HierarchicalTargetModel.from_payload(target, model_payload)
            if not self.models:
                raise ValueError("no_supported_targets")
        except Exception as exc:
            self.models = {}
            self.error = f"hierarchical_model_invalid:{type(exc).__name__}"


def predict_gated_hierarchical_outlook(
    minute_frame: Any,
    *,
    previous_close: Any,
    feed: str,
    as_of: Any = None,
    model_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Return only validation-approved hierarchical directional signals.

    The v3 model was trained on consolidated SIP minute history. We therefore
    refuse to make an actionable signal from sparse IEX input. Raw diagnostics
    are still returned when a supported artifact and SIP feature snapshot exist.
    """
    if str(feed or "").lower() != "sip":
        return {
            "available": False,
            "actionable": False,
            "model_version": MODEL_VERSION,
            "reason": "training_feed_mismatch_requires_sip",
            "signals": {},
        }

    features = extract_predictive_features(
        minute_frame,
        previous_close=previous_close,
        as_of=as_of,
    )
    registry = HierarchicalRegistry(model_path=model_path)
    if registry.error:
        return {
            "available": False,
            "actionable": False,
            "model_version": MODEL_VERSION,
            "reason": registry.error,
            "signals": {},
            "features": features,
        }

    signals: Dict[str, Any] = {}
    for target, gate in ROBUST_GATES.items():
        model = registry.models.get(target)
        if model is None:
            continue
        raw = model.predict(features)
        if raw is None:
            continue
        direction = "UP" if raw["up_given_edge"] >= 0.5 else "DOWN"
        passes = (
            raw["edge_probability"] >= gate["edge_threshold"]
            and raw["direction_confidence"] >= gate["direction_threshold"]
        )
        signals[target] = {
            "target": target,
            "actionable": bool(passes),
            "direction": direction if passes else "NO_EDGE",
            "edge_probability": round(raw["edge_probability"], 6),
            "probability_up": round(raw["probability_up"], 6),
            "probability_down": round(raw["probability_down"], 6),
            "probability_no_edge": round(raw["probability_no_edge"], 6),
            "up_given_edge": round(raw["up_given_edge"], 6),
            "down_given_edge": round(raw["down_given_edge"], 6),
            "direction_confidence": round(raw["direction_confidence"], 6),
            "imputed_feature_count": raw["imputed_feature_count"],
            "gate": gate,
            "reason": None if passes else "below_validation_approved_gate",
        }

    return {
        "available": bool(signals),
        "actionable": any(signal["actionable"] for signal in signals.values()),
        "model_version": MODEL_VERSION,
        "reason": None if signals else "required_features_or_target_missing",
        "signals": signals,
        "features": features,
        "metadata": registry.metadata,
    }
