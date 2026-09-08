from __future__ import annotations

import json
import os
from dataclasses import dataclass
from math import isfinite, log10
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd


CLASSES = ("DOWN", "NO_EDGE", "UP")
TARGETS = (
    "premarket_5m",
    "premarket_15m",
    "premarket_30m",
    "open_5m",
    "open_15m",
    "open_30m",
    "open_60m",
)

FEATURE_NAMES = (
    "gap_pct",
    "return_5m_pct",
    "return_15m_pct",
    "return_30m_pct",
    "session_return_pct",
    "vwap_distance_pct",
    "range_location",
    "range_width_pct",
    "trend_slope_pct_per_bar",
    "realized_volatility_15m",
    "realized_volatility_30m",
    "volume_acceleration",
    "log_dollar_volume",
    "elapsed_premarket_fraction",
    "bar_coverage",
)

MODEL_VERSION = "premarket_predictive_v2"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "premarket_predictive_v2.json"


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _pct_change(current: float, previous: float) -> Optional[float]:
    if previous <= 0:
        return None
    return (current / previous - 1.0) * 100.0


def _vwap(frame: pd.DataFrame) -> Optional[float]:
    volume = frame["Volume"].astype(float)
    total = float(volume.sum())
    if total <= 0:
        return None
    typical = (
        frame["High"].astype(float)
        + frame["Low"].astype(float)
        + frame["Close"].astype(float)
    ) / 3.0
    return float((typical * volume).sum() / total)


def _slope_pct_per_bar(values: Iterable[float]) -> Optional[float]:
    y = np.asarray(list(values), dtype=float)
    if y.size < 3 or not np.isfinite(y).all() or y[0] <= 0:
        return None
    x = np.arange(y.size, dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    return (slope / float(y[0])) * 100.0


def _realized_volatility(closes: pd.Series, bars: int) -> Optional[float]:
    values = closes.astype(float).tail(bars + 1)
    if len(values) < 3 or (values <= 0).any():
        return None
    returns = np.diff(np.log(values.to_numpy()))
    if returns.size < 2:
        return None
    return float(np.std(returns, ddof=1) * 100.0)


def _volume_acceleration(volume: pd.Series) -> Optional[float]:
    values = volume.astype(float).to_numpy()
    if values.size < 6:
        return None
    width = max(2, values.size // 3)
    early = float(np.mean(values[:width]))
    late = float(np.mean(values[-width:]))
    if early <= 0:
        return None
    return late / early


def _coerce_frame(frame: Any) -> Optional[pd.DataFrame]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(column not in frame.columns for column in required):
        return None
    result = frame.copy().sort_index()
    result[required] = result[required].apply(pd.to_numeric, errors="coerce")
    result = result.dropna(subset=required)
    if result.empty or (result[["Open", "High", "Low", "Close"]] <= 0).any().any():
        return None
    return result


def extract_predictive_features(
    minute_frame: Any,
    *,
    previous_close: Any,
) -> Dict[str, Optional[float]]:
    """Build a leakage-safe feature snapshot from bars observed up to now only."""
    frame = _coerce_frame(minute_frame)
    previous_close = _finite(previous_close)
    if frame is None or len(frame) < 5:
        return {name: None for name in FEATURE_NAMES}

    closes = frame["Close"].astype(float)
    current = float(closes.iloc[-1])
    first = float(frame["Open"].iloc[0])
    high = float(frame["High"].max())
    low = float(frame["Low"].min())
    pm_vwap = _vwap(frame)
    volume = frame["Volume"].astype(float)

    def trailing_return(minutes: int) -> Optional[float]:
        if len(closes) <= minutes:
            return None
        return _pct_change(current, float(closes.iloc[-(minutes + 1)]))

    typical = (
        frame["High"].astype(float)
        + frame["Low"].astype(float)
        + frame["Close"].astype(float)
    ) / 3.0
    dollar_volume = float((typical * volume).sum())
    range_location = (current - low) / (high - low) if high > low else 0.5
    reference = previous_close if previous_close and previous_close > 0 else first

    elapsed_fraction = min(1.0, max(0.0, len(frame) / 330.0))

    return {
        "gap_pct": _pct_change(current, previous_close) if previous_close and previous_close > 0 else None,
        "return_5m_pct": trailing_return(5),
        "return_15m_pct": trailing_return(15),
        "return_30m_pct": trailing_return(30),
        "session_return_pct": _pct_change(current, first),
        "vwap_distance_pct": _pct_change(current, pm_vwap) if pm_vwap and pm_vwap > 0 else None,
        "range_location": range_location,
        "range_width_pct": ((high - low) / reference) * 100.0 if reference > 0 else None,
        "trend_slope_pct_per_bar": _slope_pct_per_bar(closes.tail(60).to_numpy()),
        "realized_volatility_15m": _realized_volatility(closes, 15),
        "realized_volatility_30m": _realized_volatility(closes, 30),
        "volume_acceleration": _volume_acceleration(volume.tail(60)),
        "log_dollar_volume": log10(max(dollar_volume, 1.0)),
        "elapsed_premarket_fraction": elapsed_fraction,
        "bar_coverage": min(1.0, len(frame) / 60.0),
    }


@dataclass(frozen=True)
class CalibratedSoftmaxModel:
    target: str
    feature_names: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: np.ndarray
    temperature: float
    metrics: Dict[str, Any]

    @classmethod
    def from_dict(cls, target: str, payload: Dict[str, Any]) -> "CalibratedSoftmaxModel":
        feature_names = tuple(payload.get("feature_names") or ())
        if feature_names != FEATURE_NAMES:
            raise ValueError(f"Feature schema mismatch for {target}")
        mean = np.asarray(payload.get("mean"), dtype=float)
        scale = np.asarray(payload.get("scale"), dtype=float)
        weights = np.asarray(payload.get("weights"), dtype=float)
        bias = np.asarray(payload.get("bias"), dtype=float)
        temperature = float(payload.get("temperature", 1.0))
        n = len(feature_names)
        if mean.shape != (n,) or scale.shape != (n,) or weights.shape != (3, n) or bias.shape != (3,):
            raise ValueError(f"Invalid model dimensions for {target}")
        if temperature <= 0 or not np.isfinite(temperature):
            raise ValueError(f"Invalid temperature for {target}")
        scale = np.where(np.abs(scale) < 1e-12, 1.0, scale)
        return cls(
            target=target,
            feature_names=feature_names,
            mean=mean,
            scale=scale,
            weights=weights,
            bias=bias,
            temperature=temperature,
            metrics=dict(payload.get("metrics") or {}),
        )

    def predict(self, features: Dict[str, Optional[float]]) -> Optional[Dict[str, Any]]:
        values = [_finite(features.get(name)) for name in self.feature_names]
        missing = [name for name, value in zip(self.feature_names, values) if value is None]
        if missing:
            return None
        x = (np.asarray(values, dtype=float) - self.mean) / self.scale
        logits = (self.weights @ x + self.bias) / self.temperature
        logits = logits - float(np.max(logits))
        exp = np.exp(logits)
        probabilities = exp / float(np.sum(exp))
        p = {label: float(probabilities[index]) for index, label in enumerate(CLASSES)}
        direction = max(CLASSES, key=p.get)
        ordered = sorted(p.values(), reverse=True)
        confidence = ordered[0]
        margin = ordered[0] - ordered[1]
        return {
            "target": self.target,
            "direction": direction,
            "probability_down": round(p["DOWN"], 6),
            "probability_no_edge": round(p["NO_EDGE"], 6),
            "probability_up": round(p["UP"], 6),
            "directional_confidence": round(confidence, 6),
            "probability_margin": round(margin, 6),
            "calibrated": True,
            "temperature": self.temperature,
        }


class PremarketPredictiveRegistry:
    def __init__(self, model_path: Optional[str | Path] = None):
        configured = model_path or os.getenv("ORION_PREMARKET_MODEL_PATH") or DEFAULT_MODEL_PATH
        self.model_path = Path(configured)
        self.version: Optional[str] = None
        self.models: Dict[str, CalibratedSoftmaxModel] = {}
        self.metadata: Dict[str, Any] = {}
        self.error: Optional[str] = None
        self._load()

    @property
    def available(self) -> bool:
        return bool(self.models) and self.error is None

    def _load(self) -> None:
        if not self.model_path.exists():
            self.error = "trained_model_artifact_missing"
            return
        try:
            payload = json.loads(self.model_path.read_text(encoding="utf-8"))
            if payload.get("model_version") != MODEL_VERSION:
                raise ValueError("Unsupported premarket model version")
            self.version = payload.get("model_version")
            self.metadata = dict(payload.get("metadata") or {})
            raw_models = payload.get("targets") or {}
            for target, model_payload in raw_models.items():
                if target in TARGETS:
                    self.models[target] = CalibratedSoftmaxModel.from_dict(target, model_payload)
            if not self.models:
                raise ValueError("No supported predictive targets in artifact")
        except Exception as exc:
            self.models = {}
            self.error = f"model_artifact_invalid:{type(exc).__name__}"

    def predict(self, features: Dict[str, Optional[float]]) -> Dict[str, Any]:
        if not self.available:
            return {
                "available": False,
                "model_version": MODEL_VERSION,
                "reason": self.error or "model_unavailable",
                "forecasts": {},
            }
        forecasts = {}
        for target, model in self.models.items():
            prediction = model.predict(features)
            if prediction is not None:
                forecasts[target] = prediction
        return {
            "available": bool(forecasts),
            "model_version": self.version,
            "reason": None if forecasts else "required_features_missing",
            "forecasts": forecasts,
            "metadata": self.metadata,
        }


def predict_premarket_outlook(
    minute_frame: Any,
    *,
    previous_close: Any,
    model_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    features = extract_predictive_features(minute_frame, previous_close=previous_close)
    registry = PremarketPredictiveRegistry(model_path=model_path)
    result = registry.predict(features)
    result["features"] = features
    return result
