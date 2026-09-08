from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from premarket_directional_v4_common import (
    PREMARKET_TARGETS,
    V4_FEATURE_NAMES,
    apply_transform,
    engineer_row,
    fit_transform,
    regime_from_minutes_to_open,
)
from train_premarket_hierarchical import (
    binary_probabilities,
    fit_binary_logistic,
    fit_binary_temperature,
)


MODEL_VERSION = "premarket_directional_v5_hybrid_return"
V5_FEATURE_NAMES = V4_FEATURE_NAMES


def prepare_v5_frame(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    if target not in PREMARKET_TARGETS:
        raise ValueError(f"Unsupported v5 target: {target}")
    return_col = f"future_return_{target}_pct"
    sigma_col = f"expected_sigma_{target}_pct"
    required = [
        "ticker",
        "session_date",
        "snapshot_at",
        "minutes_to_open",
        return_col,
        sigma_col,
        *V4_FEATURE_NAMES[:17],
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing v5 columns: {', '.join(missing)}")

    work = frame[required].copy()
    work["ticker"] = work["ticker"].astype(str).str.upper().str.strip()
    work["session_date"] = pd.to_datetime(work["session_date"], errors="coerce").dt.date
    work["snapshot_at"] = pd.to_datetime(work["snapshot_at"], utc=True, errors="coerce")
    work["minutes_to_open"] = pd.to_numeric(work["minutes_to_open"], errors="coerce")
    work["future_return_pct"] = pd.to_numeric(work[return_col], errors="coerce")
    work["expected_sigma_pct"] = pd.to_numeric(work[sigma_col], errors="coerce")
    work = work.dropna(
        subset=[
            "ticker",
            "session_date",
            "snapshot_at",
            "minutes_to_open",
            "future_return_pct",
            "expected_sigma_pct",
        ]
    )
    work = work[work["expected_sigma_pct"] > 0].copy()

    engineered = pd.DataFrame([engineer_row(row) for _, row in work.iterrows()], index=work.index)
    for feature in V5_FEATURE_NAMES:
        work[feature] = pd.to_numeric(engineered[feature], errors="coerce")
    work["regime"] = work["minutes_to_open"].map(regime_from_minutes_to_open)
    work["normalized_return"] = work["future_return_pct"] / work["expected_sigma_pct"]
    work["direction_up"] = (work["future_return_pct"] > 0).astype(int)
    return work.sort_values(["session_date", "snapshot_at", "ticker"]).reset_index(drop=True)


def fit_ridge(x: np.ndarray, y: np.ndarray, *, l2: float = 3.0) -> tuple[np.ndarray, float]:
    y = np.asarray(y, dtype=float)
    center = float(np.mean(y))
    target = y - center
    gram = x.T @ x
    penalty = np.eye(x.shape[1], dtype=float) * float(l2)
    weights = np.linalg.solve(gram + penalty, x.T @ target)
    return weights, center


def ridge_predict(x: np.ndarray, weights: np.ndarray, bias: float) -> np.ndarray:
    return x @ weights + float(bias)


@dataclass(frozen=True)
class HybridModel:
    impute: np.ndarray
    mean: np.ndarray
    scale: np.ndarray
    return_weights: np.ndarray
    return_bias: float
    direction_weights: np.ndarray
    direction_bias: float
    direction_temperature: float

    def predict(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        x = apply_transform(frame, self.impute, self.mean, self.scale)
        predicted_return = ridge_predict(x, self.return_weights, self.return_bias)
        p_up = binary_probabilities(
            x,
            self.direction_weights,
            self.direction_bias,
            self.direction_temperature,
        )
        return predicted_return, p_up


def fit_hybrid_model(train: pd.DataFrame, calibration: pd.DataFrame) -> HybridModel:
    x_train, impute, mean, scale = fit_transform(train)
    x_cal = apply_transform(calibration, impute, mean, scale)

    y_return = train["future_return_pct"].to_numpy(dtype=float)
    # Clip extreme returns using train-only quantiles so isolated prints cannot dominate ridge fitting.
    lower, upper = np.quantile(y_return, [0.01, 0.99])
    y_return_clipped = np.clip(y_return, lower, upper)
    return_weights, return_bias = fit_ridge(x_train, y_return_clipped)

    y_direction = train["direction_up"].to_numpy(dtype=int)
    y_direction_cal = calibration["direction_up"].to_numpy(dtype=int)
    direction_weights, direction_bias = fit_binary_logistic(x_train, y_direction)
    direction_temperature = fit_binary_temperature(
        x_cal,
        y_direction_cal,
        direction_weights,
        direction_bias,
    )

    return HybridModel(
        impute=impute,
        mean=mean,
        scale=scale,
        return_weights=return_weights,
        return_bias=return_bias,
        direction_weights=direction_weights,
        direction_bias=direction_bias,
        direction_temperature=direction_temperature,
    )


def evaluate_gate(
    frame: pd.DataFrame,
    predicted_return: np.ndarray,
    p_up: np.ndarray,
    *,
    normalized_move_threshold: float,
    direction_confidence_threshold: float,
) -> dict:
    sigma = frame["expected_sigma_pct"].to_numpy(dtype=float)
    actual = frame["future_return_pct"].to_numpy(dtype=float)
    predicted_norm = np.abs(predicted_return) / np.maximum(sigma, 1e-9)
    confidence = np.maximum(p_up, 1.0 - p_up)
    regression_up = predicted_return > 0
    classifier_up = p_up >= 0.5
    agreement = regression_up == classifier_up
    mask = (
        agreement
        & (predicted_norm >= float(normalized_move_threshold))
        & (confidence >= float(direction_confidence_threshold))
    )
    n = int(mask.sum())
    if n == 0:
        return {
            "samples": 0,
            "coverage": 0.0,
            "directional_accuracy": None,
            "mean_signed_return_pct": None,
            "median_signed_return_pct": None,
            "positive_trade_rate": None,
        }

    predicted_sign = np.where(regression_up[mask], 1.0, -1.0)
    actual_sign = np.where(actual[mask] > 0, 1.0, -1.0)
    signed_return = actual[mask] * predicted_sign
    return {
        "samples": n,
        "coverage": round(n / len(frame), 6),
        "directional_accuracy": round(float(np.mean(predicted_sign == actual_sign)), 6),
        "mean_signed_return_pct": round(float(np.mean(signed_return)), 6),
        "median_signed_return_pct": round(float(np.median(signed_return)), 6),
        "positive_trade_rate": round(float(np.mean(signed_return > 0)), 6),
        "mean_predicted_abs_return_pct": round(float(np.mean(np.abs(predicted_return[mask]))), 6),
        "mean_direction_confidence": round(float(np.mean(confidence[mask])), 6),
    }
