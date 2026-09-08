from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from train_premarket_predictive import FEATURE_NAMES


MODEL_VERSION = "premarket_directional_v4"
PREMARKET_TARGETS = ("premarket_5m", "premarket_15m", "premarket_30m")
REGIMES = ("early", "mid", "late")

# V4 keeps the leakage-safe v2 feature snapshot, then adds only transformations
# that can be computed from the same information available at prediction time.
V4_EXTRA_FEATURES = (
    "minutes_to_open_scaled",
    "is_early",
    "is_mid",
    "is_late",
    "abs_gap_pct",
    "abs_vwap_distance_pct",
    "abs_session_return_pct",
    "abs_trend_slope",
    "momentum_5_15_agreement",
    "momentum_15_30_agreement",
    "gap_momentum_alignment",
    "vwap_momentum_alignment",
    "trend_volume_interaction",
    "trend_volatility_interaction",
    "range_volume_interaction",
    "volatility_ratio_15_30",
    "coverage_quality",
    "freshness_quality",
)
V4_FEATURE_NAMES = tuple(FEATURE_NAMES) + V4_EXTRA_FEATURES


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def regime_from_minutes_to_open(minutes_to_open: float) -> str:
    value = float(minutes_to_open)
    if value > 165:
        return "early"
    if value > 30:
        return "mid"
    return "late"


def _sign(value: float) -> float:
    if not np.isfinite(value) or value == 0:
        return 0.0
    return 1.0 if value > 0 else -1.0


def engineer_row(row: pd.Series) -> dict[str, float]:
    base = {name: finite(row.get(name)) for name in FEATURE_NAMES}
    minutes_to_open = finite(row.get("minutes_to_open"))
    if not np.isfinite(minutes_to_open):
        raise ValueError("minutes_to_open is required for v4")
    regime = regime_from_minutes_to_open(minutes_to_open)

    gap = base["gap_pct"]
    r5 = base["return_5m_pct"]
    r15 = base["return_15m_pct"]
    r30 = base["return_30m_pct"]
    session_ret = base["session_return_pct"]
    vwap = base["vwap_distance_pct"]
    trend = base["trend_slope_pct_per_minute"]
    rv15 = base["realized_volatility_15m"]
    rv30 = base["realized_volatility_30m"]
    vol_acc = base["volume_acceleration_30m"]
    range_width = base["range_width_pct"]
    cov30 = base["bar_coverage_30m"]
    cov60 = base["bar_coverage_60m"]
    age = base["last_bar_age_minutes"]

    def agreement(a, b):
        if not np.isfinite(a) or not np.isfinite(b):
            return np.nan
        return _sign(a) * _sign(b)

    def alignment(a, b):
        if not np.isfinite(a) or not np.isfinite(b):
            return np.nan
        return _sign(a) * b

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


def prepare_v4_frame(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    if target not in PREMARKET_TARGETS:
        raise ValueError(f"Unsupported v4 target: {target}")
    label_col = f"label_{target}"
    required = ["ticker", "session_date", "snapshot_at", "minutes_to_open", label_col, *FEATURE_NAMES]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing v4 columns: {', '.join(missing)}")

    work = frame[required].copy()
    work["ticker"] = work["ticker"].astype(str).str.upper().str.strip()
    work["session_date"] = pd.to_datetime(work["session_date"], errors="coerce").dt.date
    work["snapshot_at"] = pd.to_datetime(work["snapshot_at"], utc=True, errors="coerce")
    work["minutes_to_open"] = pd.to_numeric(work["minutes_to_open"], errors="coerce")
    work["label"] = work[label_col].astype(str).str.upper().str.strip()
    work = work[work["label"].isin(["UP", "DOWN", "NO_EDGE"])]
    work = work.dropna(subset=["ticker", "session_date", "snapshot_at", "minutes_to_open"])

    engineered = pd.DataFrame([engineer_row(row) for _, row in work.iterrows()], index=work.index)
    for feature in V4_FEATURE_NAMES:
        work[feature] = pd.to_numeric(engineered[feature], errors="coerce")
    work["regime"] = work["minutes_to_open"].map(regime_from_minutes_to_open)
    return work.sort_values(["session_date", "snapshot_at", "ticker"]).reset_index(drop=True)


def fit_transform(train: pd.DataFrame):
    x = train.loc[:, V4_FEATURE_NAMES].to_numpy(dtype=float)
    impute = np.nanmedian(x, axis=0)
    impute = np.where(np.isfinite(impute), impute, 0.0)
    x = np.where(np.isnan(x), impute, x)
    mean = np.mean(x, axis=0)
    scale = np.std(x, axis=0)
    scale = np.where(np.abs(scale) < 1e-12, 1.0, scale)
    return (x - mean) / scale, impute, mean, scale


def apply_transform(frame: pd.DataFrame, impute, mean, scale):
    x = frame.loc[:, V4_FEATURE_NAMES].to_numpy(dtype=float)
    x = np.where(np.isnan(x), impute, x)
    return (x - mean) / scale


def chronological_splits(work: pd.DataFrame):
    dates = sorted(work["session_date"].unique())
    if len(dates) < 40:
        raise ValueError(f"Need at least 40 session dates, found {len(dates)}")
    n = len(dates)
    train_end = max(1, int(n * 0.60))
    validation_end = max(train_end + 1, int(n * 0.75))
    calibration_end = max(validation_end + 1, int(n * 0.875))
    calibration_end = min(calibration_end, n - 1)
    groups = (
        set(dates[:train_end]),
        set(dates[train_end:validation_end]),
        set(dates[validation_end:calibration_end]),
        set(dates[calibration_end:]),
    )
    splits = tuple(work[work["session_date"].isin(group)].copy() for group in groups)
    if any(part.empty for part in splits):
        raise ValueError("Chronological split produced an empty partition")
    return splits


@dataclass(frozen=True)
class ThresholdResult:
    edge_threshold: float
    direction_threshold: float
    samples: int
    coverage: float
    accuracy: float | None
    up_precision: float | None
    down_precision: float | None
