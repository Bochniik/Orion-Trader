from datetime import datetime, timezone

import pandas as pd

from app.services.liquidity_engine import (
    LiquidityUniverseSampler,
    TIER_POLICIES,
    build_liquidity_observation,
    rank_liquidity_universe,
)


REGULAR_SESSION_NOW = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)


def history(close=100, volume=5_000_000, include_current=False):
    index = pd.date_range("2026-07-13", periods=31, freq="B")
    frame = pd.DataFrame(
        {
            "Close": [close + index * 0.1 for index in range(len(index))],
            "Volume": [volume] * len(index),
        },
        index=index,
    )
    if include_current:
        frame.loc[pd.Timestamp("2026-08-25")] = [9_999, 9_999_999_999]
    return frame


def snapshot(price=103, volume=3_000_000, trades=40_000, spread=0.02):
    return {
        "dailyBar": {
            "c": price,
            "v": volume,
            "n": trades,
            "t": "2026-08-25T15:30:00Z",
        },
        "latestTrade": {"p": price, "t": "2026-08-25T15:30:00Z"},
        "latestQuote": {
            "bp": price - spread / 2,
            "ap": price + spread / 2,
            "t": "2026-08-25T15:30:00Z",
        },
    }


def test_liquidity_metrics_use_time_adjusted_current_pace():
    result = build_liquidity_observation(
        "aapl", snapshot(), history(), now=REGULAR_SESSION_NOW
    )
    metrics = result["metrics"]

    assert result["symbol"] == "AAPL"
    assert metrics["current_dollar_volume"] == 309_000_000
    assert metrics["current_volume_rate_per_second"] == 416.666667
    assert metrics["average_volume_rate_per_second"] == 213.675214
    assert metrics["relative_volume_rate"] == 1.95
    assert metrics["trade_frequency_per_second"] == 5.555556
    assert metrics["spread_bps"] == 1.942
    assert result["liquidity_tier"] == "A"
    assert result["evidence_coverage_percent"] == 100


def test_incomplete_current_daily_row_cannot_leak_into_history_baseline():
    baseline = build_liquidity_observation(
        "TEST", snapshot(), history(), now=REGULAR_SESSION_NOW
    )
    contaminated = build_liquidity_observation(
        "TEST", snapshot(), history(include_current=True), now=REGULAR_SESSION_NOW
    )

    assert contaminated["metrics"]["average_dollar_volume_20d"] == baseline["metrics"]["average_dollar_volume_20d"]
    assert contaminated["metrics"]["average_daily_volume_20d"] == baseline["metrics"]["average_daily_volume_20d"]


def test_missing_evidence_is_null_and_scores_zero_instead_of_being_guessed():
    result = build_liquidity_observation(
        "EMPTY", {}, None, now=REGULAR_SESSION_NOW
    )

    assert result["liquidity_score"] == 0
    assert result["liquidity_tier"] == "D"
    assert result["data_status"] == "insufficient"
    assert result["metrics"]["spread_percent"] is None
    assert all(
        component["points"] == 0
        for component in result["score_components"]
    )


def test_premarket_current_rate_is_unavailable_not_extrapolated():
    before_open = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    result = build_liquidity_observation(
        "AAPL", snapshot(), history(), now=before_open
    )

    assert result["metrics"]["session_progress"]["state"] == "pre_market"
    assert result["metrics"]["current_volume_rate_per_second"] is None
    assert result["metrics"]["relative_volume_rate"] is None
    assert result["metrics"]["trade_frequency_per_second"] is None


def test_short_history_is_visible_but_cannot_earn_history_based_points():
    short = history().tail(5)
    result = build_liquidity_observation(
        "AAPL", snapshot(), short, now=REGULAR_SESSION_NOW
    )
    components = {item["id"]: item for item in result["score_components"]}

    assert result["metrics"]["history_sessions"] == 5
    assert components["average_dollar_volume"]["available"] is False
    assert components["average_dollar_volume"]["points"] == 0
    assert components["volume_rate"]["points"] == 0
    assert result["liquidity_tier"] != "A"


def test_ranking_prioritizes_tier_a_and_percentile_is_batch_relative():
    observations = {
        "EMPTY": {},
        "AAPL": snapshot(),
    }
    result = rank_liquidity_universe(
        observations,
        {"AAPL": history()},
        now=REGULAR_SESSION_NOW,
    )

    assert [row["symbol"] for row in result["rankings"]] == ["AAPL", "EMPTY"]
    assert result["rankings"][0]["liquidity_percentile"] == 100
    assert result["rankings"][1]["liquidity_percentile"] == 50
    assert result["prediction_status"]["active"] is False
    assert result["prediction_status"]["probabilities"] is None


def test_lower_liquidity_tiers_require_progressively_stronger_future_evidence():
    ordered = [TIER_POLICIES[tier] for tier in "ABCD"]

    assert [policy["minimum_directional_probability"] for policy in ordered] == sorted(
        policy["minimum_directional_probability"] for policy in ordered
    )
    assert [policy["minimum_edge_after_costs_bps"] for policy in ordered] == sorted(
        policy["minimum_edge_after_costs_bps"] for policy in ordered
    )
    assert TIER_POLICIES["D"]["default_recommendation_eligible"] is False


def test_universe_sampler_blends_live_priority_with_rotating_exploration():
    assets = [
        {"symbol": f"S{index:02}", "tradable": True, "asset_class": "us_equity"}
        for index in range(30)
    ]
    priority = [f"S{index:02}" for index in range(10)]
    sampler = LiquidityUniverseSampler()

    first = sampler.sample(assets, priority, "user-1", 10)
    second = sampler.sample(assets, priority, "user-1", 10)

    assert first["symbols"][:7] == priority[:7]
    assert first["live_activity_symbols"] == 7
    assert first["rotating_exploration_symbols"] == 3
    assert len(first["symbols"]) == 10
    assert set(first["symbols"][7:]).isdisjoint(second["symbols"][7:])
    assert first["bounded"] is True


def test_selected_ticker_is_pinned_without_removing_rotating_discovery():
    assets = [
        {"symbol": f"S{index:02}", "tradable": True, "asset_class": "us_equity"}
        for index in range(30)
    ]
    priority = [f"S{index:02}" for index in range(10)]
    result = LiquidityUniverseSampler().sample(
        assets, priority, "user-1", 10, required_symbols=["S29"]
    )

    assert result["symbols"][0] == "S29"
    assert result["required_symbols"] == ["S29"]
    assert result["required_symbols_included"] == 1
    assert result["rotating_exploration_symbols"] > 0
    assert len(result["symbols"]) == 10
