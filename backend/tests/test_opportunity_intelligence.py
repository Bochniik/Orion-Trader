import numpy as np
import pandas as pd

from app.services.opportunity_intelligence import (
    build_opportunity_intelligence,
    calibrate_opportunity_board,
    history_request_for_horizon,
    prioritize_market_structures,
)


def trend_history(rows=140, final_close=None, final_volume=1_500_000):
    close = np.linspace(80, 100, rows)
    if final_close is not None:
        close[-1] = final_close
    return pd.DataFrame(
        {
            "Open": close - 0.15,
            "High": close + 0.55,
            "Low": close - 0.55,
            "Close": close,
            "Volume": [1_000_000] * (rows - 1) + [final_volume],
        }
    )


def test_horizon_requests_use_intraday_for_day_and_deeper_daily_history():
    assert history_request_for_horizon("day") == {
        "period": "5d",
        "interval": "15m",
    }
    assert history_request_for_horizon("swing") == {
        "period": "6mo",
        "interval": "1d",
    }
    assert history_request_for_horizon("long_term") == {
        "period": "2y",
        "interval": "1d",
    }


def test_market_structure_always_returns_ordered_levels_when_data_is_sufficient():
    result = build_opportunity_intelligence(
        "swing",
        trend_history(),
        {"daily_volume": 1_500_000, "spread_percent": 0.08},
    )

    assert result["data_quality"] is True
    assert result["score"] >= 70
    assert result["trigger_status"] == "waiting_for_breakout"
    assert result["stop_loss"] < result["entry_price"] < result["take_profit"]
    assert result["breakout_price"] == result["entry_price"]
    assert result["risk_reward"] == 2.0
    assert result["support"] < result["resistance"] < result["breakout_price"]
    assert set(result["score_components"]) == {
        "trend",
        "momentum",
        "volume",
        "liquidity",
        "volatility",
        "structure",
    }


def test_breakout_requires_volume_and_rejects_chasing_an_extended_move():
    confirmed = build_opportunity_intelligence(
        "day",
        trend_history(final_close=100.85, final_volume=2_000_000),
        {"daily_volume": 2_000_000, "spread_percent": 0.05},
    )
    extended = build_opportunity_intelligence(
        "day",
        trend_history(final_close=106, final_volume=2_000_000),
        {"daily_volume": 2_000_000, "spread_percent": 0.05},
    )

    assert confirmed["trigger_status"] == "confirmed"
    assert confirmed["setup_type"] == "volume_confirmed_breakout"
    assert confirmed["entry_readiness"]["status"] == "technically_ready"
    assert confirmed["entry_readiness"]["technically_ready"] is True
    assert confirmed["entry_readiness"]["current_in_entry_zone"] is True
    assert all(
        check["passed"] for check in confirmed["entry_readiness"]["checks"]
    )
    assert extended["trigger_status"] == "extended"
    assert extended["entry_readiness"]["technically_ready"] is False
    assert extended["entry_readiness"]["status"] == "extended"
    assert any("retest" in warning.lower() for warning in extended["warnings"])


def test_missing_history_fails_closed_without_inventing_prices():
    result = build_opportunity_intelligence("long_term", pd.DataFrame())

    assert result["data_quality"] is False
    assert result["trigger_status"] == "data_insufficient"
    assert result["entry_readiness"]["status"] == "data_insufficient"
    assert result["entry_readiness"]["technically_ready"] is False
    assert result["entry_price"] is None
    assert result["breakout_price"] is None
    assert result["stop_loss"] is None


def test_deterministic_prefilter_prefers_confirmed_structure_over_raw_volume():
    items = [
        {
            "candidate": {"symbol": "LOUD", "daily_volume": 50_000_000},
            "market_structure": {
                "data_quality": True,
                "trigger_status": "extended",
                "score": 90,
            },
        },
        {
            "candidate": {"symbol": "CLEAN", "daily_volume": 2_000_000},
            "market_structure": {
                "data_quality": True,
                "trigger_status": "confirmed",
                "score": 78,
            },
        },
    ]

    assert prioritize_market_structures(items)[0]["candidate"]["symbol"] == "CLEAN"


def test_entry_ready_prefilter_prioritizes_complete_readiness_audit():
    items = [
        {
            "candidate": {"symbol": "WATCH", "daily_volume": 20_000_000},
            "market_structure": {
                "data_quality": True,
                "trigger_status": "confirmed",
                "score": 92,
                "entry_readiness": {"technically_ready": False},
            },
        },
        {
            "candidate": {"symbol": "READY", "daily_volume": 2_000_000},
            "market_structure": {
                "data_quality": True,
                "trigger_status": "confirmed",
                "score": 78,
                "entry_readiness": {"technically_ready": True},
            },
        },
    ]

    ordered = prioritize_market_structures(
        items, setup_filter="entry_ready"
    )

    assert ordered[0]["candidate"]["symbol"] == "READY"


def test_catalyst_prefilter_prioritizes_observed_readiness_score():
    items = [
        {
            "candidate": {"symbol": "STRUCTURE", "daily_volume": 20_000_000},
            "market_structure": {
                "data_quality": True,
                "trigger_status": "confirmed",
                "score": 95,
            },
            "breakout_readiness": {"score": 40, "coverage_percent": 100},
        },
        {
            "candidate": {"symbol": "CATALYST", "daily_volume": 2_000_000},
            "market_structure": {
                "data_quality": True,
                "trigger_status": "waiting_for_breakout",
                "score": 72,
            },
            "breakout_readiness": {"score": 85, "coverage_percent": 90},
        },
    ]

    ordered = prioritize_market_structures(
        items, setup_filter="catalyst_breakout"
    )

    assert ordered[0]["candidate"]["symbol"] == "CATALYST"


def test_hybrid_calibration_caps_model_confidence_when_structure_is_missing():
    board = {
        "horizon": "swing",
        "candidates": [
            {
                "symbol": "AAPL",
                "research_rating": "STRONG_CANDIDATE",
                "score": 96,
            }
        ],
    }
    evidence = [
        {
            "candidate": {"symbol": "AAPL"},
            "market_structure": {
                "data_quality": False,
                "score": 0,
                "trigger_status": "data_insufficient",
                "summary": "No history",
            },
        }
    ]

    result = calibrate_opportunity_board(board, evidence, "swing")
    candidate = result["candidates"][0]

    assert candidate["model_score"] == 96
    assert candidate["score"] == 54
    assert candidate["research_rating"] == "AVOID"
    assert result["best_setup"]["decision_state"] == "data_insufficient"
    assert result["ranking_version"] == "hybrid-ranking-v1"


def test_hybrid_calibration_drops_unknown_duplicates_and_fails_closed_on_omissions():
    structure = {
        "version": "market-structure-v1",
        "data_quality": True,
        "score": 80,
        "trigger_status": "confirmed",
        "entry_price": 100,
        "breakout_price": 100,
        "stop_loss": 95,
        "take_profit": 110,
        "summary": "Confirmed.",
    }
    board = {
        "candidates": [
            {
                "symbol": "FAKE",
                "research_rating": "STRONG_CANDIDATE",
                "score": 100,
            },
            {
                "symbol": "AAPL",
                "research_rating": "WATCH",
                "score": 76,
            },
            {
                "symbol": "AAPL",
                "research_rating": "STRONG_CANDIDATE",
                "score": 99,
            },
        ]
    }
    evidence = [
        {"candidate": {"symbol": "AAPL"}, "market_structure": structure},
        {"candidate": {"symbol": "MSFT"}, "market_structure": structure},
    ]

    result = calibrate_opportunity_board(board, evidence, "day")
    by_symbol = {item["symbol"]: item for item in result["candidates"]}

    assert set(by_symbol) == {"AAPL", "MSFT"}
    assert by_symbol["AAPL"]["model_score"] == 76
    assert by_symbol["MSFT"]["model_score"] == 0
    assert by_symbol["MSFT"]["research_rating"] == "AVOID"
    assert "fails closed" in by_symbol["MSFT"]["thesis"]
