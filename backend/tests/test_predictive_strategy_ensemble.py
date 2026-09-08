from app.services.predictive_strategy_ensemble import analyze_strategy_ensemble


def bullish_snapshot():
    return {
        "price": 100,
        "features": {
            "ema_9": 101, "ema_20": 100,
            "ema_9_slope": 0.002, "ema_20_slope": 0.001,
            "sma_9_slope": 0.002, "sma_20_slope": 0.001,
            "return_1m": 0.001, "return_3m": 0.003, "return_5m": 0.005,
            "momentum_acceleration": 0.0002,
            "distance_from_vwap": 0.002, "vwap_reclaim_rejection": 1,
            "rsi_14": 58, "volatility_ratio": 1.3,
            "relative_volume": 1.8, "volume_acceleration": 0.4,
            "quote_imbalance": 0.25, "opening_range_position": 1.1,
            "distance_from_intraday_high": -0.001,
            "distance_from_intraday_low": 0.02,
            "distance_from_previous_day_high": 0.003,
            "distance_from_previous_day_low": 0.03,
            "relative_strength_market": 0.003, "index_momentum": 0.001,
        },
    }


def test_fourteen_strategy_families_form_a_deterministic_bullish_consensus():
    result = analyze_strategy_ensemble(bullish_snapshot())

    assert result["strategy_count"] == 14
    assert result["available_strategies"] == 14
    assert result["consensus"] == "LONG"
    assert result["agreement_score"] > 55
    assert result["probabilities_modified"] is False
    assert all(item["formula"] for item in result["strategies"])


def test_learning_can_only_adjust_strategy_weight_inside_bounded_range():
    result = analyze_strategy_ensemble(
        bullish_snapshot(),
        learned_profiles={
            "ema_trend": {
                "observations": 100,
                "reliability_multiplier": 99,
            },
            "volume_momentum": {
                "observations": 100,
                "reliability_multiplier": -5,
            },
        },
    )
    rows = {item["id"]: item for item in result["strategies"]}

    assert rows["ema_trend"]["learned_multiplier"] == 1.25
    assert rows["volume_momentum"]["learned_multiplier"] == 0.75
    assert result["probabilities_modified"] is False


def test_missing_features_are_visible_and_cannot_create_false_consensus():
    result = analyze_strategy_ensemble({"price": 100, "features": {}})

    assert result["available_strategies"] == 0
    assert result["consensus"] == "NEUTRAL"
    assert all(item["state"] == "UNAVAILABLE" for item in result["strategies"])

