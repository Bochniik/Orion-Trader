"""Accelerated, causal market replay for Orion forward-learning research.

The replay engine deliberately keeps simulated evidence outside the live-forward
persistence path.  It hard-cuts all model inputs at the virtual clock before
calling the production forward adapter, then reveals the historical future only
when a prediction's target timestamp has matured.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

import pandas as pd

from app.services.intraday_probability_long_horizon_v5_forward import (
    FORWARD_ADAPTER_ID,
    estimate_long_horizon_v5_frame,
)

SIMULATED_FORWARD = "SIMULATED_FORWARD"
LIVE_FORWARD = "LIVE_FORWARD"
REPLAY_ENGINE_ID = "market-replay-v2"

ForwardPredictor = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ReplayConfig:
    """Deterministic replay controls.

    ``stride_bars`` controls how often the virtual clock asks Orion for a new
    forecast. ``warmup_bars`` prevents obviously under-seeded calls.  The
    production adapter remains responsible for deciding whether its own feature
    and training history are sufficient.
    """

    stride_bars: int = 1
    warmup_bars: int = 1
    scope: str = SIMULATED_FORWARD

    def __post_init__(self) -> None:
        if self.scope != SIMULATED_FORWARD:
            raise ValueError("Market replay may only emit SIMULATED_FORWARD evidence")
        if int(self.stride_bars) < 1:
            raise ValueError("stride_bars must be >= 1")
        if int(self.warmup_bars) < 1:
            raise ValueError("warmup_bars must be >= 1")


def _utc_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _flatten_single_symbol_columns(frame: pd.DataFrame, *, name: str) -> pd.DataFrame:
    """Normalize yfinance single-ticker MultiIndex OHLCV into scalar columns.

    Newer yfinance versions commonly return columns such as ``('Close', 'AAPL')``
    even for one ticker.  Orion's forward adapter already normalizes that shape,
    but replay settlement/reference-price extraction also needs the same canonical
    scalar ``Close`` column.  Multiple symbols in one frame are deliberately
    rejected rather than silently selecting the wrong ticker.
    """
    if not isinstance(frame.columns, pd.MultiIndex):
        return frame

    result = frame.copy()
    flattened = [column[0] if isinstance(column, tuple) else column for column in result.columns]
    if len(set(flattened)) != len(flattened):
        raise ValueError(f"{name} contains ambiguous multi-symbol market columns")
    result.columns = flattened
    return result


def _validated_frame(frame: pd.DataFrame, *, name: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{name} must be a non-empty DataFrame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError(f"{name} must use a DatetimeIndex")

    result = _flatten_single_symbol_columns(frame.copy(), name=name)
    index = result.index
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    result.index = index

    if result.index.has_duplicates:
        raise ValueError(f"{name} contains duplicate timestamps")
    if not result.index.is_monotonic_increasing:
        raise ValueError(f"{name} timestamps must be monotonically increasing")
    return result


def _causal_slice(frame: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Return only observations visible at the virtual replay clock."""
    cutoff = _utc_timestamp(as_of)
    return frame.loc[frame.index <= cutoff].copy()


def _price_at(frame: pd.DataFrame, timestamp: pd.Timestamp) -> float | None:
    target = _utc_timestamp(timestamp)
    if target not in frame.index:
        return None
    row = frame.loc[target]
    if isinstance(row, pd.DataFrame):
        return None
    try:
        value = float(row["Close"])
    except (KeyError, TypeError, ValueError):
        return None
    if not pd.notna(value) or value <= 0:
        return None
    return value


def _actual_direction(realized_return: float) -> str:
    if realized_return > 0:
        return "bullish"
    if realized_return < 0:
        return "bearish"
    return "neutral"


def _prediction_record(
    *,
    symbol: str,
    prediction_time: pd.Timestamp,
    reference_price: float,
    horizon: str,
    horizon_result: dict[str, Any],
    forecast: dict[str, Any],
) -> dict[str, Any]:
    target = _utc_timestamp(horizon_result["target_time_utc"])
    probability_up = float(horizon_result["probability_up"])
    probability_down = float(horizon_result["probability_down"])
    return {
        "scope": SIMULATED_FORWARD,
        "replay_engine_id": REPLAY_ENGINE_ID,
        "symbol": symbol,
        "prediction_time_utc": _utc_timestamp(prediction_time).isoformat(),
        "target_time_utc": target.isoformat(),
        "horizon": str(horizon),
        "reference_price": float(reference_price),
        "probability_up": probability_up,
        "probability_down": probability_down,
        "direction": horizon_result.get("direction"),
        "design_id": forecast.get("design_id"),
        "model_version": forecast.get("design_id"),
        "forward_adapter_id": forecast.get("forward_adapter_id") or FORWARD_ADAPTER_ID,
        "training_samples": horizon_result.get("training_samples"),
        "training_cutoff": horizon_result.get("training_cutoff"),
        "max_training_timestamp": horizon_result.get("max_training_timestamp"),
        "status": "pending",
        "settled_at_utc": None,
        "future_price": None,
        "realized_return": None,
        "actual_direction": None,
        "direction_correct": None,
        "brier_up": None,
    }


def settle_replay_prediction(
    prediction: dict[str, Any],
    historical_stock: pd.DataFrame,
    *,
    replay_clock: Any,
) -> dict[str, Any]:
    """Settle one replay prediction only after its horizon has matured.

    The caller may hold the complete historical frame, but this function refuses
    to reveal the target value while the virtual clock is earlier than target.
    """
    if prediction.get("scope") != SIMULATED_FORWARD:
        raise ValueError("Replay settlement accepts SIMULATED_FORWARD evidence only")

    historical_stock = _validated_frame(historical_stock, name="historical_stock")
    target = _utc_timestamp(prediction["target_time_utc"])
    clock = _utc_timestamp(replay_clock)
    if clock < target:
        return {**prediction, "status": "pending"}

    future_price = _price_at(historical_stock, target)
    if future_price is None:
        return {
            **prediction,
            "status": "unresolved",
            "settled_at_utc": clock.isoformat(),
            "reason": "no_exact_historical_close_at_target",
        }

    reference = float(prediction["reference_price"])
    realized_return = future_price / reference - 1.0
    actual = _actual_direction(realized_return)
    predicted = prediction.get("direction")
    correct = None if predicted == "neutral" else bool(predicted == actual)
    actual_up = 1.0 if realized_return > 0 else 0.0
    probability_up = float(prediction["probability_up"])

    return {
        **prediction,
        "status": "settled",
        "settled_at_utc": clock.isoformat(),
        "future_price": future_price,
        "realized_return": realized_return,
        "actual_direction": actual,
        "direction_correct": correct,
        "brier_up": (probability_up - actual_up) ** 2,
        "reason": None,
    }


class MarketReplayEngine:
    """Chronologically replay historical bars through Orion's live forward adapter."""

    def __init__(
        self,
        *,
        predictor: ForwardPredictor = estimate_long_horizon_v5_frame,
        config: ReplayConfig | None = None,
    ) -> None:
        self.predictor = predictor
        self.config = config or ReplayConfig()

    def run(
        self,
        stock: pd.DataFrame,
        benchmark: pd.DataFrame,
        *,
        symbol: str,
        decision_times: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        ticker = str(symbol or "").strip().upper()
        if not ticker:
            raise ValueError("symbol is required")

        stock = _validated_frame(stock, name="stock")
        benchmark = _validated_frame(benchmark, name="benchmark")

        if decision_times is None:
            candidates = list(stock.index[self.config.warmup_bars - 1 :: self.config.stride_bars])
        else:
            candidates = sorted({_utc_timestamp(value) for value in decision_times})

        predictions: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []

        for clock in candidates:
            clock = _utc_timestamp(clock)
            stock_visible = _causal_slice(stock, clock)
            benchmark_visible = _causal_slice(benchmark, clock)
            if stock_visible.empty or benchmark_visible.empty:
                unavailable.append({"as_of": clock.isoformat(), "reason": "no_visible_market_data"})
                continue

            # Hard anti-leakage boundary: the predictor never receives a row whose
            # timestamp is later than the virtual replay clock.
            forecast = self.predictor(
                stock_visible,
                benchmark_visible,
                symbol=ticker,
                as_of=clock,
            )
            if not isinstance(forecast, dict) or not forecast.get("available"):
                unavailable.append(
                    {
                        "as_of": clock.isoformat(),
                        "reason": (forecast or {}).get("reason", "forecast_unavailable")
                        if isinstance(forecast, dict)
                        else "invalid_forecast",
                    }
                )
                continue

            as_of = _utc_timestamp(forecast.get("as_of", clock))
            if as_of > clock:
                raise RuntimeError("Predictor violated replay cutoff: forecast as_of is in the future")
            reference_price = _price_at(stock_visible, as_of)
            if reference_price is None:
                unavailable.append({"as_of": clock.isoformat(), "reason": "missing_reference_close"})
                continue

            for horizon, horizon_result in (forecast.get("horizons") or {}).items():
                if not isinstance(horizon_result, dict) or not horizon_result.get("available"):
                    continue
                target = _utc_timestamp(horizon_result["target_time_utc"])
                if target <= as_of:
                    raise RuntimeError("Predictor returned a non-forward target timestamp")
                predictions.append(
                    _prediction_record(
                        symbol=ticker,
                        prediction_time=as_of,
                        reference_price=reference_price,
                        horizon=horizon,
                        horizon_result=horizon_result,
                        forecast=forecast,
                    )
                )

        # Settlement is a separate phase.  No target price was exposed to the
        # predictor.  Advancing to the end of supplied history merely resolves
        # predictions whose horizons genuinely matured inside that history.
        replay_end = stock.index[-1]
        settled = [
            settle_replay_prediction(row, stock, replay_clock=replay_end)
            for row in predictions
        ]

        status_counts: dict[str, int] = {}
        for row in settled:
            status = str(row.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        resolved = [row for row in settled if row.get("status") == "settled"]
        mean_brier = (
            sum(float(row["brier_up"]) for row in resolved) / len(resolved)
            if resolved
            else None
        )
        directional = [row for row in resolved if row.get("direction_correct") is not None]
        directional_accuracy = (
            sum(bool(row["direction_correct"]) for row in directional) / len(directional)
            if directional
            else None
        )

        return {
            "scope": SIMULATED_FORWARD,
            "replay_engine_id": REPLAY_ENGINE_ID,
            "symbol": ticker,
            "predictor_adapter_id": FORWARD_ADAPTER_ID,
            "start_time_utc": stock.index[0].isoformat(),
            "end_time_utc": stock.index[-1].isoformat(),
            "decision_point_count": len(candidates),
            "prediction_count": len(settled),
            "status_counts": status_counts,
            "resolved_prediction_count": len(resolved),
            "mean_brier_up": mean_brier,
            "directional_accuracy": directional_accuracy,
            "predictions": settled,
            "unavailable_decision_points": unavailable,
            "live_forward_mutated": False,
            "anti_leakage": {
                "hard_input_cutoff": True,
                "future_revealed_only_at_settlement": True,
                "simulated_live_separation": True,
            },
        }
