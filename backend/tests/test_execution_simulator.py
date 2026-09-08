import pytest

from app.services.execution_simulator import simulate_execution_stress


def plan(**overrides):
    values = {
        "symbol": "TEST",
        "side": "buy",
        "order_type": "market",
        "quantity": 1_000,
        "reference_price": 20,
        "daily_volume": 1_000_000,
        "spread_bps": 10,
        "base_slippage_bps": 5,
        "max_participation_percent": 1,
        "adverse_gap_percent": 8,
        "luld_style_band_percent": 5,
        "protective_stop_price": 18,
    }
    values.update(overrides)
    return simulate_execution_stress(**values)


def scenario(result, scenario_id):
    return next(item for item in result["scenarios"] if item["id"] == scenario_id)


def test_execution_matrix_is_deterministic_research_only_and_non_probabilistic():
    result = plan()

    assert result["version"] == "execution-stress-v1"
    assert len(result["scenarios"]) == 7
    assert result["probability_model"]["probabilities"] is None
    assert result["regulatory_context"]["official_band_replay"] is False
    assert "No broker credentials" in result["safety_boundary"]
    assert scenario(result, "baseline")["status"] == "filled"


def test_spread_and_gap_stresses_never_improve_buy_execution_cost():
    result = plan(adverse_gap_percent=4)
    baseline = scenario(result, "baseline")
    wide = scenario(result, "wide_spread")
    gap = scenario(result, "opening_gap")

    assert wide["implementation_shortfall_bps"] > baseline["implementation_shortfall_bps"]
    assert gap["implementation_shortfall_bps"] > wide["implementation_shortfall_bps"]
    assert gap["cost_breakdown"]["adverse_gap"] > 0


def test_participation_cap_produces_auditable_partial_fill():
    result = plan(quantity=50_000, daily_volume=100_000, max_participation_percent=1)
    baseline = scenario(result, "baseline")
    thin = scenario(result, "thin_liquidity")

    assert baseline["status"] == "partial_fill"
    assert baseline["filled_quantity"] == 1_000
    assert thin["filled_quantity"] == 250
    assert thin["unfilled_quantity"] == 49_750


def test_limit_price_can_block_or_partially_constrain_the_fill():
    blocked = plan(
        order_type="limit", limit_price=20.005, protective_stop_price=None,
    )
    permissive = plan(
        order_type="limit", limit_price=20.10, protective_stop_price=None,
    )

    assert scenario(blocked, "baseline")["status"] == "limit_not_marketable"
    assert scenario(blocked, "baseline")["average_fill_price"] is None
    assert scenario(permissive, "baseline")["filled_quantity"] > 0
    assert scenario(permissive, "baseline")["average_fill_price"] <= 20.10


def test_pause_and_rejection_never_invent_a_fill_or_zero_cost():
    result = plan()
    paused = scenario(result, "luld_interruption")
    rejected = scenario(result, "broker_rejection")
    combined = scenario(result, "combined_stress")

    for item in (paused, rejected, combined):
        assert item["filled_quantity"] == 0
        assert item["average_fill_price"] is None
        assert item["implementation_shortfall"] is None
        assert item["immediate_execution_allowed"] is False
    assert paused["status"] == "paused_no_immediate_fill"
    assert rejected["status"] == "rejected"


def test_stop_stress_expands_risk_under_an_adverse_gap():
    result = plan(adverse_gap_percent=12, luld_style_band_percent=20)
    baseline = scenario(result, "baseline")["stop_stress"]
    gap = scenario(result, "opening_gap")["stop_stress"]

    assert baseline["modeled_stop_fill_price"] < baseline["planned_stop_price"]
    assert gap["stressed_risk_per_share"] > baseline["stressed_risk_per_share"]
    assert gap["risk_expansion_multiple"] > 1


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"quantity": float("nan")}, "finite"),
        ({"daily_volume": 0}, "Daily volume"),
        ({"order_type": "limit", "limit_price": None}, "Limit price is required"),
        ({"order_type": "market", "limit_price": 20}, "must be omitted"),
        ({"protective_stop_price": 21}, "below the reference"),
    ],
)
def test_invalid_plans_fail_closed(overrides, message):
    with pytest.raises(ValueError, match=message):
        plan(**overrides)
