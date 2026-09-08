from __future__ import annotations

import json
import os
from dataclasses import dataclass
from math import isfinite, log10
from pathlib import Path
from typing import Any, Dict, Optional

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

# Raw live features. Missing values are allowed: the trained artifact stores
# train-only medians used for imputation so a sparse IEX premarket feed does
# not discard an otherwise useful snapshot.
FEATURE_NAMES = (
    "gap_pct",
    "return_5m_pct",
    "return_15m_pct",
    "return_30m_pct",
    "session_return_pct",
    "vwap_distance_pct",
    "range_location",
    "range_width_pct",
    "trend_slope_pct_per_minute",
    "realized_volatility_15m",
    "realized_volatility_30m",
    "volume_acceleration_30m",
    "log_dollar_volume",
    "elapsed_premarket_fraction",
    "bar_coverage_30m",
    "bar_coverage_60m",
    "last_bar_age_minutes",
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


def _coerce_frame(frame: Any) -> Optional[pd.DataFrame]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(column not in frame.columns for column in required):
        return None
    result = frame.copy()
    if not isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.to_datetime(result.index, utc=True, errors="coerce")
    if result.index.tz is None:
        result.index = result.index.tz_localize("UTC")
    result = result.loc[~result.index.isna()].sort_index()
    result[required] = result[required].apply(pd.to_numeric, errors="coerce")
    result = result.dropna(subset=required)
    if result.empty or (result[["Open", "High", "Low", "Close"]] <= 0).any().any():
        return None
    return result


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


def _price_at_or_before(
    frame: pd.DataFrame,
    target: pd.Timestamp,
    *,
    max_age_minutes: float,
) -> Optional[float]:
    eligible = frame.loc[frame.index <= target]
    if eligible.empty:
        return None
    stamp = eligible.index[-1]
    age = (target - stamp).total_seconds() / 60.0
    if age < 0 or age > max_age_minutes:
        return None
    return float(eligible["Close"].iloc[-1])


def _time_window(frame: pd.DataFrame, as_of: pd.Timestamp, minutes: int) -> pd.DataFrame:
    return frame.loc[(frame.index > as_of - pd.Timedelta(minutes=minutes)) & (frame.index <= as_of)]


def _slope_pct_per_minute(frame: pd.DataFrame) -> Optional[float]:
    if len(frame) < 3:
        return None
    closes = frame["Close"].astype(float).to_numpy()
    if not np.isfinite(closes).all() or closes[0] <= 0:
        return None
    stamps = frame.index.view("int64").astype(float) / 60_000_000_000.0
    x = stamps - stamps[0]
    if float(np.ptp(x)) <= 0:
        return None
    slope = float(np.polyfit(x, closes, 1)[0])
    return (slope / closes[0]) * 100.0


def _realized_volatility(frame: pd.DataFrame) -> Optional[float]:
    if len(frame) < 3:
        return None
    closes = frame["Close"].astype(float).to_numpy()
    if (closes <= 0).any():
        return None
    returns = np.diff(np.log(closes))
    if returns.size < 2:
        return None
    return float(np.std(returns, ddof=1) * 100.0)


def _volume_acceleration_30m(frame: pd.DataFrame, as_of: pd.Timestamp) -> Optional[float]:
    window = _time_window(frame, as_of, 30)
    if len(window) < 4:
        return None
    midpoint = as_of - pd.Timedelta(minutes=15)
    early = float(window.loc[window.index <= midpoint, "Volume"].sum())
    late = float(window.loc[window.index > midpoint, "Volume"].sum())
    if early <= 0:
        return None
    return late / early


def _coverage(frame: pd.DataFrame, as_of: pd.Timestamp, minutes: int) -> float:
    count = len(_time_window(frame, as_of, minutes))
    return float(min(1.0, max(0.0, count / float(minutes))))


def extract_predictive_features(
    minute_frame: Any,
    *,
    previous_close: Any,
    as_of: Any = None,
) -> Dict[str, Optional[float]]:
    """Build a leakage-safe feature snapshot using clock time, not bar count.

    Sparse feeds such as Alpaca IEX do not emit one bar for every wall-clock
    minute in premarket. Therefore all 5/15/30-minute features are defined by
    timestamps. Missing observations remain missing and are imputed only by a
    train-only median stored inside the model artifact.
    """
    frame = _coerce_frame(minute_frame)
    previous_close = _finite(previous_close)
    if frame is None or len(frame) < 3:
        return {name: None for name in FEATURE_NAMES}

    if as_of is None:
        as_of_ts = pd.Timestamp(frame.index[-1])
    else:
        as_of_ts = pd.Timestamp(as_of)
        if as_of_ts.tzinfo is None:
            as_of_ts = as_of_ts.tz_localize("UTC")
        as_of_ts = as_of_ts.tz_convert(frame.index.tz)

    observed = frame.loc[frame.index <= as_of_ts]
    if len(observed) < 3:
        return {name: None for name in FEATURE_NAMES}

    last_stamp = observed.index[-1]
    current = float(observed["Close"].iloc[-1])
    first = float(observed["Open"].iloc[0])
    high = float(observed["High"].max())
    low = float(observed["Low"].min())
    pm_vwap = _vwap(observed)
    volume = observed["Volume"].astype(float)

    def trailing_return(minutes: int) -> Optional[float]:
        # Permit a moderately stale reference on sparse feeds, but never use a
        # bar that is wildly outside the intended lookback horizon.
        reference_at = as_of_ts - pd.Timedelta(minutes=minutes)
        reference = _price_at_or_before(
            observed,
            reference_at,
            max_age_minutes=max(5.0, minutes * 0.75),
        )
        return _pct_change(current, reference) if reference and reference > 0 else None

    typical = (
        observed["High"].astype(float)
        + observed["Low"].astype(float)
        + observed["Close"].astype(float)
    ) / 3.0
    dollar_volume = float((typical * volume).sum())
    range_location = (current - low) / (high - low) if high > low else 0.5
    reference_price = previous_close if previous_close and previous_close > 0 else first

    local_as_of = as_of_ts.tz_convert("America/New_York")
    session_start = local_as_of.normalize() + pd.Timedelta(hours=4)
    regular_open = local_as_of.normalize() + pd.Timedelta(hours=9, minutes=30)
    elapsed = (local_as_of - session_start).total_seconds() / 60.0
    total_pm = (regular_open - session_start).total_seconds() / 60.0
    elapsed_fraction = float(min(1.0, max(0.0, elapsed / total_pm)))

    window15 = _time_window(observed, as_of_ts, 15)
    window30 = _time_window(observed, as_of_ts, 30)
    window60 = _time_window(observed, as_of_ts, 60)
    age_minutes = max(0.0, (as_of_ts - last_stamp).total_seconds() / 60.0)

    return {
        "gap_pct": _pct_change(current, previous_close) if previous_close and previous_close > 0 else None,
        "return_5m_pct": trailing_return(5),
        "return_15m_pct": trailing_return(15),
        "return_30m_pct": trailing_return(30),
        "session_return_pct": _pct_change(current, first),
        "vwap_distance_pct": _pct_change(current, pm_vwap) if pm_vwap and pm_vwap > 0 else None,
        "range_location": range_location,
        "range_width_pct": ((high - low) / reference_price) * 100.0 if reference_price > 0 else None,
        "trend_slope_pct_per_minute": _slope_pct_per_minute(window60),
        "realized_volatility_15m": _realized_volatility(window15),
        "realized_volatility_30m": _realized_volatility(window30),
        "volume_acceleration_30m": _volume_acceleration_30m(observed, as_of_ts),
        "log_dollar_volume": log10(max(dollar_volume, 1.0)),
        "elapsed_premarket_fraction": elapsed_fraction,
        "bar_coverage_30m": _coverage(observed, as_of_ts, 30),
        "bar_coverage_60m": _coverage(observed, as_of_ts, 60),
        "last_bar_age_minutes": float(age_minutes),
    }


@dataclass(frozen=True)
class CalibratedSoftmaxModel:
    target: str
    feature_names: tuple[str, ...]
    impute: np.ndarray
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
        impute = np.asarray(payload.get("impute"), dtype=float)
        mean = np.asarray(payload.get("mean"), dtype=float)
        scale = np.asarray(payload.get("scale"), dtype=float)
        weights = np.asarray(payload.get("weights"), dtype=float)
        bias = np.asarray(payload.get("bias"), dtype=float)
        temperature = float(payload.get("temperature", 1.0))
        n = len(feature_names)
        if impute.shape != (n,) or mean.shape != (n,) or scale.shape != (n,) or weights.shape != (3, n) or bias.shape != (3,):
            raise ValueError(f"Invalid model dimensions for {target}")
        if temperature <= 0 or not np.isfinite(temperature):
            raise ValueError(f"Invalid temperature for {target}")
        scale = np.where(np.abs(scale) < 1e-12, 1.0, scale)
        return cls(
            target=target,
            feature_names=feature_names,
            impute=impute,
            mean=mean,
            scale=scale,
            weights=weights,
            bias=bias,
            temperature=temperature,
            metrics=dict(payload.get("metrics") or {}),
        )

    def predict(self, features: Dict[str, Optional[float]]) -> Optional[Dict[str, Any]]:
        values = np.asarray([
            np.nan if _finite(features.get(name)) is None else float(features.get(name))
            for name in self.feature_names
        ], dtype=float)
        missing_count = int(np.isnan(values).sum())
        if missing_count > max(5, len(values) // 2):
            return None
        values = np.where(np.isnan(values), self.impute, values)
        x = (values - self.mean) / self.scale
        logits = (self.weights @ x + self.bias) / self.temperature
        logits = logits - float(np.max(logits))
        exp = np.exp(logits)
        probabilities = exp / float(np.sum(exp))
        p = {label: float(probabilities[index]) for index, label in enumerate(CLASSES)}
        direction = max(CLASSES, key=p.get)
        ordered = sorted(p.values(), reverse=True)
        return {
            "target": self.target,
            "direction": direction,
            "probability_down": round(p["DOWN"], 6),
            "probability_no_edge": round(p["NO_EDGE"], 6),
            "probability_up": round(p["UP"], 6),
            "directional_confidence": round(ordered[0], 6),
            "probability_margin": round(ordered[0] - ordered[1], 6),
            "calibrated": True,
            "temperature": self.temperature,
            "imputed_feature_count": missing_count,
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
    as_of: Any = None,
    model_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    features = extract_predictive_features(
        minute_frame,
        previous_close=previous_close,
        as_of=as_of,
    )
    registry = PremarketPredictiveRegistry(model_path=model_path)
    result = registry.predict(features)
    result["features"] = features
    return result
