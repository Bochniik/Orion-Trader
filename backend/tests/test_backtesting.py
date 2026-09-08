import pandas as pd
import pytest

from app.services.backtesting import BacktestEngine


def history(prices):
    return pd.DataFrame(
        {
            "Open": prices,
            "High": [price + 1 for price in prices],
            "Low": [price - 1 for price in prices],
            "Close": prices,
            "Volume": [1_000] * len(prices),
        },
        index=pd.date_range("2025-01-01", periods=len(prices), freq="D", tz="UTC"),
    )


def test_sma_backtest_is_deterministic_and_models_friction():
    prices = list(range(140, 90, -1)) + list(range(90, 150)) + list(range(150, 110, -1))
    engine = BacktestEngine()
    first = engine.run("AAPL", history(prices), "sma_crossover", {"fast_period": 5, "slow_period": 15}, commission_bps=10, slippage_bps=10)
    second = engine.run("AAPL", history(prices), "sma_crossover", {"fast_period": 5, "slow_period": 15}, commission_bps=10, slippage_bps=10)
    assert first == second
    assert first["metrics"]["completed_trades"] >= 1
    assert first["assumptions"]["signal_execution"] == "next bar open"
    assert first["equity_curve"][0]["time"] == "2025-01-02"


def test_backtest_validates_strategy_and_history():
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="Unsupported"):
        engine.run("AAPL", history([100] * 40), "magic")
    with pytest.raises(ValueError, match="Slow SMA"):
        engine.run("AAPL", history([100] * 40), "sma_crossover", {"fast_period": 20, "slow_period": 10})
    with pytest.raises(ValueError, match="Allocation"):
        engine.run("AAPL", history([100] * 40), "breakout", {"allocation_percent": 0})
