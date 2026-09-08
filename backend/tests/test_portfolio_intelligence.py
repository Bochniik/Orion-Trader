import pandas as pd
import pytest

from app.services.portfolio_intelligence import (
    aggregate_exposure,
    build_benchmark_comparison,
    calculate_performance_metrics,
    simulate_position_size,
    simulate_rebalance,
)


def test_exposure_aggregates_sector_and_asset_class():
    positions = {
        "AAPL": {"market_value": 600, "sector": "Technology", "asset_type": "Stock"},
        "MSFT": {"market_value": 400, "sector": "Technology", "asset_type": "Stock"},
        "SPY": {"market_value": 1_000, "sector": "Diversified", "asset_type": "ETF"},
    }
    result = aggregate_exposure(positions)
    assert result["sectors"][0] == {"name": "Technology", "market_value": 1000.0, "percent": 50.0}
    assert result["asset_classes"][0]["name"] == "Stock"


def test_performance_metrics_calculate_drawdown_volatility_and_sharpe():
    history = [
        {"total_value": 100},
        {"total_value": 110},
        {"total_value": 99},
        {"total_value": 120},
    ]
    result = calculate_performance_metrics(history)
    assert result["total_return_percent"] == 20
    assert result["max_drawdown_percent"] == -10
    assert result["annualized_volatility_percent"] is not None
    assert result["sharpe_ratio"] is not None
    assert result["status"] == "ready"


def test_benchmark_comparison_normalizes_both_series():
    history = [
        {"date": "2026-01-01", "total_value": 100},
        {"date": "2026-01-02", "total_value": 110},
    ]
    frame = pd.DataFrame(
        {"Close": [200, 210]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
    )
    result = build_benchmark_comparison(history, "SPY", frame)
    assert result["portfolio_return_percent"] == 10
    assert result["benchmark_return_percent"] == 5
    assert result["status"] == "ready"


def test_position_sizing_respects_risk_cash_and_allocation_limits():
    result = simulate_position_size(10_000, 2_000, 100, 95, 1, 10)
    assert result["recommended_shares"] == 10
    assert result["risk_amount"] == 50
    assert result["limiting_factor"] == "allocation"
    with pytest.raises(ValueError, match="below entry"):
        simulate_position_size(10_000, 2_000, 100, 100, 1, 10)


def test_rebalancing_returns_actions_without_executing_trades():
    snapshot = {
        "total_value": 10_000,
        "positions": {
            "AAPL": {"market_value": 6_000, "current_price": 100},
            "MSFT": {"market_value": 2_000, "current_price": 200},
        },
    }
    result = simulate_rebalance(snapshot, {"AAPL": 40, "MSFT": 40, "CASH": 20})
    assert result["actions"][0]["action"] == "SELL"
    assert result["actions"][1]["action"] == "BUY"
    assert result["simulation_only"] is True
