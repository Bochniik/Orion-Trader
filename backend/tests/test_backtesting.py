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


def test_backtest_audits_commission_slippage_and_spread_separately():
    bars = history([100] * 40)

    def run_with_costs(**costs):
        engine = BacktestEngine()

        def signals(frame, kind, parameters):
            entry = pd.Series(False, index=frame.index)
            exit_signal = pd.Series(False, index=frame.index)
            entry.iloc[0] = True
            exit_signal.iloc[1] = True
            return entry, exit_signal

        engine._signals = signals
        cost_assumptions = {
            "commission_bps": 0,
            "slippage_bps": 0,
            "spread_bps": 0,
        }
        cost_assumptions.update(costs)
        return engine.run(
            "AAPL",
            bars,
            "breakout",
            **cost_assumptions,
        )

    no_cost = run_with_costs()
    commission_only = run_with_costs(commission_bps=10)
    slippage_only = run_with_costs(slippage_bps=10)
    spread_only = run_with_costs(spread_bps=20)

    assert commission_only["metrics"]["final_equity"] < no_cost["metrics"]["final_equity"]
    assert commission_only["metrics"]["final_equity"] == slippage_only["metrics"]["final_equity"]
    assert commission_only["metrics"]["final_equity"] == spread_only["metrics"]["final_equity"]
    assert spread_only["assumptions"]["commission_bps"] == 0
    assert spread_only["assumptions"]["slippage_bps"] == 0
    assert spread_only["assumptions"]["spread_bps"] == 20
    assert spread_only["assumptions"]["spread_application"] == "half_spread_each_side"
    assert spread_only["assumptions"]["per_side_friction_bps"] == 10


def test_backtest_rejects_invalid_spread_assumptions():
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="friction assumptions"):
        engine.run("AAPL", history([100] * 40), "breakout", spread_bps=-1)
    with pytest.raises(ValueError, match="friction assumptions"):
        engine.run("AAPL", history([100] * 40), "breakout", spread_bps=1_001)


def test_liquidity_spread_scenarios_are_hypothetical_and_cost_sensitive():
    engine = BacktestEngine()
    bars = history([100] * 40)

    def signals(frame, kind, parameters):
        entry = pd.Series(False, index=frame.index)
        exit_signal = pd.Series(False, index=frame.index)
        entry.iloc[0] = True
        exit_signal.iloc[1] = True
        return entry, exit_signal

    engine._signals = signals
    result = engine.run_liquidity_spread_scenarios(
        "AAPL",
        bars,
        "breakout",
        {"A": 2, "D": 100},
        commission_bps=0,
        slippage_bps=0,
    )

    assert result["evidence_type"] == "hypothetical_cost_sensitivity"
    assert result["historical_quotes_used"] is False
    assert result["promotion_eligible"] is False
    assert result["scenarios"]["A"]["spread_bps"] == 2
    assert result["scenarios"]["D"]["spread_bps"] == 100
    assert (
        result["scenarios"]["D"]["metrics"]["final_equity"]
        < result["scenarios"]["A"]["metrics"]["final_equity"]
    )


@pytest.mark.parametrize(
    "scenarios",
    [
        {},
        {"E": 10},
        {"A": "unknown"},
        {"A": float("inf")},
        {"A": -1},
        {"A": 1_001},
        {"a": 5, "A": 10},
    ],
)
def test_liquidity_spread_scenarios_fail_closed(scenarios):
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="Liquidity spread"):
        engine.run_liquidity_spread_scenarios(
            "AAPL",
            history([100] * 40),
            "breakout",
            scenarios,
        )
