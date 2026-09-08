from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from math import isfinite, log
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.intraday_probability_engine import (
    FEATURE_COLUMNS,
    HORIZONS,
    HORIZON_MINUTES,
    NEW_YORK,
    SEMANTICS,
    _attach_targets,
    _build_features,
    _estimate_one_horizon,
    _normalize_ohlcv,
)


BACKTEST_SEMANTICS = (
    "Chronological walk-forward validation of OrionTrader intraday directional "
    "probabilities. Every prediction uses only historical examples whose target "
    "outcome was already fully resolved before the prediction timestamp. "
    "No random train/test split is used."
)


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _binary_log_loss(y: np.ndarray, p: np.ndarray) -> float:
    if len(y) == 0:
        return float("nan")
    eps = 1e-9
    p = np.clip(p, eps, 1.0 - eps)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def _brier_score(y: np.ndarray, p: np.ndarray) -> float:
    if len(y) == 0:
        return float("nan")
    return float(np.mean((p - y) ** 2))


def _calibration_bins(
    records: List[Dict[str, Any]],
    *,
    bin_width: int = 10,
) -> List[Dict[str, Any]]:
    if not records:
        return []

    bins: List[Dict[str, Any]] = []

    for low in range(0, 100, bin_width):
        high = low + bin_width
        selected = [
            row
            for row in records
            if (
                row.get("probability_up") is not None
                and (
                    low <= float(row["probability_up"]) < high
                    or (high == 100 and float(row["probability_up"]) == 100.0)
                )
            )
        ]

        if not selected:
            continue

        predicted = np.array(
            [float(row["probability_up"]) / 100.0 for row in selected],
            dtype=float,
        )
        actual = np.array(
            [float(row["actual_up"]) for row in selected],
            dtype=float,
        )

        avg_pred = float(np.mean(predicted))
        actual_rate = float(np.mean(actual))

        bins.append(
            {
                "range": f"{low}-{high}",
                "count": len(selected),
                "average_predicted_up_pct": round(avg_pred * 100.0, 2),
                "actual_up_rate_pct": round(actual_rate * 100.0, 2),
                "calibration_gap_pct": round((actual_rate - avg_pred) * 100.0, 2),
            }
        )

    return bins


def _expected_calibration_error(
    bins: List[Dict[str, Any]],
) -> Optional[float]:
    total = sum(int(item["count"]) for item in bins)
    if total <= 0:
        return None

    weighted = 0.0

    for item in bins:
        weight = int(item["count"]) / total
        gap = abs(float(item["calibration_gap_pct"])) / 100.0
        weighted += weight * gap

    return round(weighted * 100.0, 3)


def _summarize_horizon(
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not records:
        return {
            "available": False,
            "prediction_count": 0,
            "reason": "No resolved walk-forward predictions.",
        }

    y = np.array(
        [float(row["actual_up"]) for row in records],
        dtype=float,
    )
    p = np.array(
        [float(row["probability_up"]) / 100.0 for row in records],
        dtype=float,
    )

    predicted_direction = np.where(
        p >= 0.55,
        1,
        np.where(p <= 0.45, 0, -1),
    )

    directional_mask = predicted_direction >= 0

    if np.any(directional_mask):
        directional_accuracy = float(
            np.mean(
                predicted_direction[directional_mask]
                == y[directional_mask]
            )
        )
    else:
        directional_accuracy = float("nan")

    all_accuracy = float(
        np.mean(
            (p >= 0.5).astype(float) == y
        )
    )

    confident_60_mask = (p >= 0.60) | (p <= 0.40)
    confident_65_mask = (p >= 0.65) | (p <= 0.35)

    def _confident_stats(mask: np.ndarray) -> Dict[str, Any]:
        count = int(np.sum(mask))
        if count == 0:
            return {
                "count": 0,
                "accuracy_pct": None,
            }

        pred = (p[mask] >= 0.5).astype(float)
        return {
            "count": count,
            "accuracy_pct": round(
                float(np.mean(pred == y[mask])) * 100.0,
                2,
            ),
        }

    bins = _calibration_bins(records)
    ece = _expected_calibration_error(bins)

    probability_mean = float(np.mean(p))
    actual_up_rate = float(np.mean(y))

    expected_return = np.array(
        [
            float(row.get("expected_return_pct") or 0.0)
            for row in records
        ],
        dtype=float,
    )
    realized_return = np.array(
        [
            float(row.get("realized_return_pct") or 0.0)
            for row in records
        ],
        dtype=float,
    )

    if len(expected_return) > 1 and np.std(expected_return) > 0 and np.std(realized_return) > 0:
        return_correlation = float(
            np.corrcoef(
                expected_return,
                realized_return,
            )[0, 1]
        )
    else:
        return_correlation = float("nan")

    return {
        "available": True,
        "prediction_count": len(records),
        "actual_up_rate_pct": round(actual_up_rate * 100.0, 2),
        "average_predicted_up_pct": round(probability_mean * 100.0, 2),
        "accuracy_at_50_pct": round(all_accuracy * 100.0, 2),
        "directional_prediction_count": int(np.sum(directional_mask)),
        "directional_accuracy_pct": (
            round(directional_accuracy * 100.0, 2)
            if isfinite(directional_accuracy)
            else None
        ),
        "confident_60": _confident_stats(confident_60_mask),
        "confident_65": _confident_stats(confident_65_mask),
        "brier_score": round(_brier_score(y, p), 5),
        "log_loss": round(_binary_log_loss(y, p), 5),
        "expected_calibration_error_pct": ece,
        "expected_vs_realized_return_correlation": (
            round(return_correlation, 4)
            if isfinite(return_correlation)
            else None
        ),
        "calibration_bins": bins,
    }


def _prediction_timestamps(
    dataset: pd.DataFrame,
    *,
    initial_training_days: int,
    stride_bars: int,
) -> List[pd.Timestamp]:
    if dataset.empty:
        return []

    local_index = dataset.index.tz_convert(NEW_YORK)
    dates = pd.Series(local_index.date, index=dataset.index)

    unique_dates = list(dict.fromkeys(dates.tolist()))

    if len(unique_dates) <= initial_training_days:
        return []

    first_test_date = unique_dates[initial_training_days]

    eligible = dataset.loc[
        dates >= first_test_date
    ].dropna(
        subset=FEATURE_COLUMNS
    )

    if eligible.empty:
        return []

    stride_bars = max(1, int(stride_bars))
    return list(eligible.index[::stride_bars])


def walk_forward_backtest_frame(
    frame: pd.DataFrame,
    *,
    symbol: str = "TEST",
    initial_training_days: int = 15,
    stride_bars: int = 6,
    neighbor_count: int = 180,
    min_samples: int = 80,
    max_predictions_per_horizon: Optional[int] = None,
) -> Dict[str, Any]:
    """Run leakage-safe chronological walk-forward validation.

    Leakage protection:
    - Test timestamps move forward chronologically.
    - For a horizon H, analog candidates must begin at least H minutes before
      the test timestamp. Therefore their outcome was already fully resolved.
    - Future targets never cross the 16:00 ET regular-session boundary because
      intraday_probability_engine._attach_targets enforces same-session labels.
    """

    normalized = _normalize_ohlcv(frame)

    if normalized.empty:
        return {
            "symbol": symbol.upper(),
            "available": False,
            "warnings": ["No usable regular-session OHLCV data."],
            "semantics": BACKTEST_SEMANTICS,
        }

    dataset = _attach_targets(
        _build_features(
            normalized
        )
    )

    test_timestamps = _prediction_timestamps(
        dataset,
        initial_training_days=initial_training_days,
        stride_bars=stride_bars,
    )

    if not test_timestamps:
        return {
            "symbol": symbol.upper(),
            "available": False,
            "bar_count": len(normalized),
            "warnings": [
                "Insufficient chronological history after the initial training window."
            ],
            "semantics": BACKTEST_SEMANTICS,
        }

    records_by_horizon: Dict[str, List[Dict[str, Any]]] = {
        label: []
        for label in HORIZONS
    }

    skipped_by_horizon: Dict[str, int] = {
        label: 0
        for label in HORIZONS
    }

    for timestamp in test_timestamps:
        current = dataset.loc[timestamp]

        if isinstance(current, pd.DataFrame):
            current = current.iloc[-1]

        if current[FEATURE_COLUMNS].isna().any():
            continue

        for label in HORIZONS:
            if (
                max_predictions_per_horizon is not None
                and len(records_by_horizon[label]) >= max_predictions_per_horizon
            ):
                continue

            target_up_col = f"target_up_{label}"
            target_return_col = f"target_return_{label}"

            actual_up = _safe_float(
                current.get(
                    target_up_col
                )
            )
            realized_return = _safe_float(
                current.get(
                    target_return_col
                )
            )

            if actual_up is None or realized_return is None:
                skipped_by_horizon[label] += 1
                continue

            resolution_cutoff = (
                pd.Timestamp(timestamp)
                - pd.Timedelta(
                    minutes=HORIZON_MINUTES[label]
                )
            )

            history = dataset.loc[
                dataset.index <= resolution_cutoff
            ].copy()

            estimate = _estimate_one_horizon(
                history,
                current,
                label,
                neighbor_count=neighbor_count,
                min_samples=min_samples,
            )

            if not estimate.get("available"):
                skipped_by_horizon[label] += 1
                continue

            records_by_horizon[label].append(
                {
                    "timestamp": pd.Timestamp(timestamp).isoformat(),
                    "probability_up": estimate.get("probability_up"),
                    "probability_down": estimate.get("probability_down"),
                    "direction": estimate.get("direction"),
                    "directional_confidence": estimate.get("directional_confidence"),
                    "expected_return_pct": estimate.get("expected_return_pct"),
                    "evidence_quality": estimate.get("evidence_quality"),
                    "neighbors_used": estimate.get("neighbors_used"),
                    "effective_sample_size": estimate.get("effective_sample_size"),
                    "actual_up": int(actual_up),
                    "realized_return_pct": round(realized_return * 100.0, 4),
                }
            )

    horizon_metrics = {
        label: _summarize_horizon(records)
        for label, records in records_by_horizon.items()
    }

    prediction_total = sum(
        len(records)
        for records in records_by_horizon.values()
    )

    available = prediction_total > 0

    return {
        "symbol": symbol.upper(),
        "available": available,
        "method": "chronological_walk_forward_same_session_nearest_analogs",
        "bar_count": len(normalized),
        "test_timestamp_count": len(test_timestamps),
        "initial_training_days": initial_training_days,
        "stride_bars": stride_bars,
        "neighbor_count": neighbor_count,
        "min_samples": min_samples,
        "horizons": horizon_metrics,
        "skipped_predictions": skipped_by_horizon,
        "interpretation": {
            "brier_score": (
                "Lower is better. 0 is perfect; 0.25 corresponds roughly to "
                "always predicting 50% in a balanced binary problem."
            ),
            "log_loss": "Lower is better; strongly penalizes overconfident wrong forecasts.",
            "expected_calibration_error_pct": (
                "Lower is better. Measures how far predicted probability bins "
                "are from their observed hit rates."
            ),
            "directional_accuracy_pct": (
                "Accuracy only when the model actually called bullish >=55% "
                "or bearish <=45%; neutral predictions are excluded."
            ),
            "confident_60": (
                "Performance when P(up)>=60% or P(up)<=40%."
            ),
            "confident_65": (
                "Performance when P(up)>=65% or P(up)<=35%."
            ),
        },
        "warnings": [
            "This validates the current 60-day-style analog model; it is not yet a multi-year production study.",
            "Results can vary materially across tickers and market regimes.",
            "Use calibration and accuracy metrics together; a high raw hit rate alone is not enough.",
        ],
        "semantics": BACKTEST_SEMANTICS,
    }


def walk_forward_backtest(
    symbol: str,
    *,
    period: str = "60d",
    interval: str = "5m",
    initial_training_days: int = 15,
    stride_bars: int = 6,
    neighbor_count: int = 180,
    min_samples: int = 80,
    max_predictions_per_horizon: Optional[int] = None,
) -> Dict[str, Any]:
    ticker = str(symbol or "").strip().upper()

    if not ticker:
        raise ValueError("symbol is required")

    try:
        import yfinance as yf
    except Exception as exc:
        return {
            "symbol": ticker,
            "available": False,
            "warnings": [
                f"yfinance import failed: {type(exc).__name__}"
            ],
            "semantics": BACKTEST_SEMANTICS,
        }

    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        return {
            "symbol": ticker,
            "available": False,
            "warnings": [
                f"Historical data request failed: {type(exc).__name__}"
            ],
            "semantics": BACKTEST_SEMANTICS,
        }

    result = walk_forward_backtest_frame(
        raw,
        symbol=ticker,
        initial_training_days=initial_training_days,
        stride_bars=stride_bars,
        neighbor_count=neighbor_count,
        min_samples=min_samples,
        max_predictions_per_horizon=max_predictions_per_horizon,
    )

    result["period"] = period
    result["interval"] = interval

    return result


def _synthetic_frame() -> pd.DataFrame:
    rng = np.random.default_rng(20260905)
    sessions = []

    business_days = pd.bdate_range(
        "2026-03-02",
        periods=58,
    )

    price = 100.0

    for day_index, day in enumerate(business_days):
        index = pd.date_range(
            pd.Timestamp(
                day.date(),
                tz=NEW_YORK,
            )
            + pd.Timedelta(
                hours=9,
                minutes=30,
            ),
            periods=78,
            freq="5min",
        )

        regime = (
            0.00030
            if day_index % 6 in {0, 1, 2}
            else -0.00018
        )

        noise = rng.normal(
            0.0,
            0.0014,
            len(index),
        )

        returns = (
            regime
            + 0.20 * np.r_[0.0, noise[:-1]]
            + noise
        )

        close = price * np.cumprod(
            1.0 + returns
        )
        open_ = np.r_[price, close[:-1]]

        wick = np.abs(
            rng.normal(
                0.0009,
                0.0003,
                len(index),
            )
        )

        high = np.maximum(
            open_,
            close,
        ) * (1.0 + wick)

        low = np.minimum(
            open_,
            close,
        ) * (1.0 - wick)

        volume = rng.integers(
            400_000,
            2_500_000,
            len(index),
        )

        sessions.append(
            pd.DataFrame(
                {
                    "Open": open_,
                    "High": high,
                    "Low": low,
                    "Close": close,
                    "Volume": volume,
                },
                index=index,
            )
        )

        price = float(
            close[-1]
        )

    return pd.concat(
        sessions
    )


def _self_test() -> Dict[str, Any]:
    frame = _synthetic_frame()

    return walk_forward_backtest_frame(
        frame,
        symbol="SYNTHETIC",
        initial_training_days=15,
        stride_bars=12,
        neighbor_count=120,
        min_samples=60,
        max_predictions_per_horizon=100,
    )


if __name__ == "__main__":
    import json
    import sys

    if "--self-test" in sys.argv:
        output = _self_test()
    else:
        ticker = (
            sys.argv[1].upper()
            if len(sys.argv) > 1
            else "NVDA"
        )

        output = walk_forward_backtest(
            ticker
        )

    print(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
