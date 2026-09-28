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


def test_backtest_rejects_reversed_or_duplicate_bar_timestamps():
    engine = BacktestEngine()
    ordered = history([100] * 40)

    reversed_history = ordered.iloc[::-1]
    with pytest.raises(ValueError, match="strictly increasing unique"):
        engine.run("AAPL", reversed_history, "breakout")

    duplicate_history = ordered.copy()
    duplicate_index = list(duplicate_history.index)
    duplicate_index[-1] = duplicate_index[-2]
    duplicate_history.index = duplicate_index
    with pytest.raises(ValueError, match="strictly increasing unique"):
        engine.run("AAPL", duplicate_history, "breakout")


def test_backtest_rejects_non_finite_non_positive_or_inconsistent_ohlc():
    engine = BacktestEngine()
    valid = history([100] * 40)

    invalid_histories = []

    non_finite = valid.copy()
    non_finite.iloc[0, non_finite.columns.get_loc("Open")] = float("inf")
    invalid_histories.append(non_finite)

    non_positive = valid.copy()
    non_positive.iloc[0, non_positive.columns.get_loc("Low")] = 0
    invalid_histories.append(non_positive)

    inconsistent = valid.copy()
    inconsistent.iloc[0, inconsistent.columns.get_loc("High")] = 99
    invalid_histories.append(inconsistent)

    for invalid in invalid_histories:
        with pytest.raises(ValueError, match="finite, positive, internally consistent"):
            engine.run("AAPL", invalid, "breakout")


def test_backtest_uses_conservative_stop_first_policy_for_intrabar_conflict():
    engine = BacktestEngine()
    bars = history([100] * 40)
    bars.iloc[2, bars.columns.get_loc("High")] = 120
    bars.iloc[2, bars.columns.get_loc("Low")] = 80

    def signals(frame, kind, parameters):
        entry = pd.Series(False, index=frame.index)
        entry.iloc[0] = True
        return entry, pd.Series(False, index=frame.index)

    engine._signals = signals
    result = engine.run(
        "AAPL",
        bars,
        "breakout",
        {"stop_loss_percent": 10, "take_profit_percent": 10},
        commission_bps=0,
        slippage_bps=0,
    )

    assert result["trades"][0]["exit_reason"] == "stop_loss"
    assert result["trades"][0]["exit_price"] == 90
    assert (
        result["assumptions"]["intrabar_stop_take_conflict"]
        == "stop_loss_first_conservative"
    )


@pytest.mark.parametrize(
    ("gap_open", "bar_low", "bar_high", "expected_reason", "expected_price"),
    [
        (120, 80, 121, "take_profit", 120),
        (80, 79, 120, "stop_loss", 80),
    ],
)
def test_backtest_executes_opening_gap_before_intrabar_range(
    gap_open, bar_low, bar_high, expected_reason, expected_price
):
    engine = BacktestEngine()
    bars = history([100] * 40)
    bars.iloc[2, bars.columns.get_loc("Open")] = gap_open
    bars.iloc[2, bars.columns.get_loc("Low")] = bar_low
    bars.iloc[2, bars.columns.get_loc("High")] = bar_high

    def signals(frame, kind, parameters):
        entry = pd.Series(False, index=frame.index)
        entry.iloc[0] = True
        return entry, pd.Series(False, index=frame.index)

    engine._signals = signals
    result = engine.run(
        "AAPL",
        bars,
        "breakout",
        {"stop_loss_percent": 10, "take_profit_percent": 10},
        commission_bps=0,
        slippage_bps=0,
    )

    assert result["trades"][0]["exit_reason"] == expected_reason
    assert result["trades"][0]["exit_price"] == expected_price
    assert (
        result["assumptions"]["gap_execution"]
        == "opening_price_before_intrabar_range"
    )
