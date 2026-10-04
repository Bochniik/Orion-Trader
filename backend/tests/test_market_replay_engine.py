from __future__ import annotations

import pandas as pd
import pytest

from app.services.market_replay_engine import (
    LIVE_FORWARD,
    SIMULATED_FORWARD,
    MarketReplayEngine,
    ReplayConfig,
    settle_replay_prediction,
)


def _bars(count: int = 8) -> pd.DataFrame:
    index = pd.date_range("2026-01-02T14:30:00Z", periods=count, freq="5min")
    close = [100.0 + i for i in range(count)]
    return pd.DataFrame(
        {
            "Open": close,
            "High": [value + 0.5 for value in close],
            "Low": [value - 0.5 for value in close],
            "Close": close,
            "Volume": [1000 + i for i in range(count)],
        },
        index=index,
    )


def test_replay_predictor_never_receives_future_rows():
    stock = _bars()
    benchmark = _bars()
    seen = []

    def predictor(stock_visible, benchmark_visible, *, symbol, as_of):
        seen.append(
            {
                "clock": pd.Timestamp(as_of),
                "stock_max": stock_visible.index.max(),
                "benchmark_max": benchmark_visible.index.max(),
            }
        )
        return {"available": False, "reason": "probe"}

    engine = MarketReplayEngine(predictor=predictor, config=ReplayConfig(stride_bars=2))
    result = engine.run(stock, benchmark, symbol="TEST")

    assert seen
    assert result["scope"] == SIMULATED_FORWARD
    assert result["live_forward_mutated"] is False
    for row in seen:
        assert row["stock_max"] <= row["clock"]
        assert row["benchmark_max"] <= row["clock"]


def test_replay_prediction_remains_pending_before_target_maturity():
    stock = _bars()
    prediction = {
        "scope": SIMULATED_FORWARD,
        "target_time_utc": stock.index[4].isoformat(),
        "reference_price": float(stock.iloc[0]["Close"]),
        "probability_up": 0.7,
        "direction": "bullish",
        "status": "pending",
    }

    result = settle_replay_prediction(
        prediction,
        stock,
        replay_clock=stock.index[3],
    )

    assert result["status"] == "pending"
    assert result.get("future_price") is None
    assert result.get("realized_return") is None


def test_replay_prediction_settles_only_after_target_maturity():
    stock = _bars()
    prediction = {
        "scope": SIMULATED_FORWARD,
        "target_time_utc": stock.index[4].isoformat(),
        "reference_price": float(stock.iloc[0]["Close"]),
        "probability_up": 0.7,
        "direction": "bullish",
        "status": "pending",
    }

    result = settle_replay_prediction(
        prediction,
        stock,
        replay_clock=stock.index[4],
    )

    assert result["status"] == "settled"
    assert result["future_price"] == float(stock.iloc[4]["Close"])
    assert result["realized_return"] > 0
    assert result["actual_direction"] == "bullish"
    assert result["direction_correct"] is True
    assert result["brier_up"] == pytest.approx((0.7 - 1.0) ** 2)


def test_replay_rejects_live_forward_scope():
    with pytest.raises(ValueError, match="SIMULATED_FORWARD"):
        ReplayConfig(scope=LIVE_FORWARD)

    stock = _bars()
    with pytest.raises(ValueError, match="SIMULATED_FORWARD"):
        settle_replay_prediction(
            {
                "scope": LIVE_FORWARD,
                "target_time_utc": stock.index[1].isoformat(),
                "reference_price": 100.0,
                "probability_up": 0.5,
                "direction": "neutral",
            },
            stock,
            replay_clock=stock.index[-1],
        )


def test_replay_preserves_model_version_and_settles_fake_forward_adapter():
    stock = _bars()
    benchmark = _bars()
    decision_time = stock.index[2]
    target_time = stock.index[4]

    def predictor(stock_visible, benchmark_visible, *, symbol, as_of):
        assert stock_visible.index.max() == decision_time
        assert benchmark_visible.index.max() == decision_time
        return {
            "available": True,
            "as_of": decision_time.isoformat(),
            "design_id": "fake-model-v1",
            "forward_adapter_id": "fake-forward-v1",
            "horizons": {
                "10m": {
                    "available": True,
                    "probability_up": 0.75,
                    "probability_down": 0.25,
                    "direction": "bullish",
                    "target_time_utc": target_time.isoformat(),
                    "training_samples": 123,
                    "training_cutoff": stock.index[0].isoformat(),
                    "max_training_timestamp": stock.index[1].isoformat(),
                }
            },
        }

    engine = MarketReplayEngine(predictor=predictor)
    result = engine.run(
        stock,
        benchmark,
        symbol="test",
        decision_times=[decision_time],
    )

    assert result["prediction_count"] == 1
    record = result["predictions"][0]
    assert record["scope"] == SIMULATED_FORWARD
    assert record["model_version"] == "fake-model-v1"
    assert record["forward_adapter_id"] == "fake-forward-v1"
    assert record["status"] == "settled"
    assert record["training_samples"] == 123


def test_replay_rejects_non_monotonic_or_duplicate_input():
    duplicate = _bars().copy()
    duplicate.index = list(duplicate.index[:-1]) + [duplicate.index[-2]]
    with pytest.raises(ValueError, match="duplicate"):
        MarketReplayEngine().run(duplicate, _bars(), symbol="TEST")

    non_monotonic = _bars().iloc[[0, 2, 1, 3, 4, 5, 6, 7]]
    with pytest.raises(ValueError, match="monotonically increasing"):
        MarketReplayEngine().run(non_monotonic, _bars(), symbol="TEST")
