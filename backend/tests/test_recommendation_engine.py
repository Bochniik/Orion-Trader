import pytest

from app.services.recommendation_engine import (
    build_trade_recommendation,
    get_recommendation_profile,
    list_recommendation_profiles,
)


def candidate(score=92, rating="STRONG_CANDIDATE", entry=100, stop=98, target=105):
    return {
        "symbol": "AAPL",
        "score": score,
        "research_rating": rating,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": target,
    }


def market(**overrides):
    return {
        "price": 100,
        "spread_percent": 0.10,
        "daily_volume": 2_000_000,
        "change_percent": 3,
        "partial_failure": False,
        **overrides,
    }


def portfolio(equity=100_000, cash=100_000):
    return {"total_value": equity, "cash": cash}


def test_profiles_are_bounded_and_all_modes_fail_closed_on_leverage():
    profiles = list_recommendation_profiles()

    assert [profile["mode"] for profile in profiles] == ["conservative", "balanced", "aggressive"]
    assert profiles[0]["max_instrument_leverage"] == 1
    assert [profile["max_instrument_leverage"] for profile in profiles] == [1, 1, 1]
    assert all(profile["cfd_horizons"] == [] for profile in profiles)
    with pytest.raises(ValueError, match="conservative, balanced, or aggressive"):
        get_recommendation_profile("maximum")


def test_balanced_uses_unlevered_risk_budget_even_for_strong_setup():
    plan = build_trade_recommendation("day", candidate(), market(), portfolio(), "balanced")

    assert plan["status"] == "qualified"
    assert plan["instrument"] == "REAL_SHARES"
    assert plan["suggested_leverage"] == 1
    assert plan["quantity"] == 150
    assert plan["notional_exposure"] == 15_000
    assert plan["estimated_margin"] == 15_000
    assert plan["estimated_max_loss"] <= plan["risk_budget"]
    assert plan["external_execution_only"] is True


def test_aggressive_mode_never_increases_leverage_before_validation():
    plan = build_trade_recommendation(
        "day",
        candidate(score=96, target=106),
        market(spread_percent=0.10, change_percent=5),
        portfolio(),
        "aggressive",
    )
    less_exceptional = build_trade_recommendation(
        "day",
        candidate(score=93, target=106),
        market(spread_percent=0.10, change_percent=5),
        portfolio(),
        "aggressive",
    )

    assert plan["suggested_leverage"] == 1
    assert plan["estimated_margin"] == plan["notional_exposure"]
    assert less_exceptional["suggested_leverage"] == 1
    assert any(gate["name"] == "borrowed_exposure_validation" and gate["passed"] is False for gate in plan["gates"])


def test_wide_spread_does_not_enable_borrowed_exposure():
    plan = build_trade_recommendation(
        "day",
        candidate(),
        market(spread_percent=0.8),
        portfolio(),
        "balanced",
    )

    assert plan["status"] == "qualified"
    assert plan["instrument"] == "REAL_SHARES"
    assert plan["suggested_leverage"] == 1
    assert plan["estimated_margin"] == plan["notional_exposure"]
    assert any(gate["name"] == "borrowed_exposure_validation" and gate["passed"] is False for gate in plan["gates"])
    assert any("CFD suggestions are disabled" in warning for warning in plan["warnings"])


def test_watch_stale_or_invalid_levels_cannot_receive_a_position_plan():
    watch = build_trade_recommendation("day", candidate(rating="WATCH"), market(), portfolio(), "aggressive")
    stale = build_trade_recommendation("day", candidate(), market(partial_failure=True), portfolio(), "aggressive")
    invalid = build_trade_recommendation("day", candidate(stop=101), market(), portfolio(), "aggressive")

    assert watch["status"] == "not_qualified"
    assert stale["status"] == "data_insufficient"
    assert invalid["status"] == "data_insufficient"
    for plan in (watch, stale, invalid):
        assert plan["instrument"] == "NO_TRADE"
        assert plan["quantity"] == 0


def test_long_term_research_remains_unlevered_in_aggressive_mode():
    plan = build_trade_recommendation(
        "long_term",
        candidate(score=98, target=110),
        market(),
        portfolio(),
        "aggressive",
    )

    assert plan["status"] == "qualified"
    assert plan["instrument"] == "REAL_SHARES"
    assert plan["suggested_leverage"] == 1
    assert any(gate["name"] == "borrowed_exposure_validation" and gate["passed"] is False for gate in plan["gates"])


def test_cross_currency_position_sizing_fails_closed_without_fx_conversion():
    plan = build_trade_recommendation(
        "swing",
        candidate(),
        market(instrument_currency="USD"),
        {**portfolio(), "currency": "EUR"},
        "balanced",
    )

    assert plan["status"] == "sizing_unavailable"
    assert plan["quantity"] == 0
    assert any(
        gate["name"] == "currency_conversion" and gate["passed"] is False
        for gate in plan["gates"]
    )


def test_cross_currency_position_sizing_uses_explicit_fx_rate():
    plan = build_trade_recommendation(
        "swing",
        candidate(),
        market(
            instrument_currency="USD",
            instrument_to_account_rate=0.85,
        ),
        {**portfolio(), "currency": "EUR"},
        "balanced",
    )

    assert plan["status"] == "qualified"
    assert plan["account_currency"] == "EUR"
    assert plan["instrument_currency"] == "USD"
    assert plan["instrument_to_account_rate"] == 0.85
    assert plan["notional_exposure"] == pytest.approx(
        plan["quantity"] * 100 * 0.85
    )


def test_waiting_breakout_keeps_concrete_levels_but_never_sizes_a_trade():
    planned = candidate()
    planned["level_plan"] = {
        "version": "market-structure-v1",
        "data_quality": True,
        "trigger_status": "waiting_for_breakout",
        "current_price": 98,
        "entry_price": 100,
        "entry_zone_low": 99.8,
        "entry_zone_high": 100.2,
        "breakout_price": 100,
        "stop_loss": 97,
        "take_profit": 106,
        "summary": "Wait for the breakout.",
    }

    plan = build_trade_recommendation(
        "swing", planned, market(price=98), portfolio(), "balanced"
    )

    assert plan["status"] == "awaiting_trigger"
    assert plan["quantity"] == 0
    assert plan["entry_price"] == 100
    assert plan["breakout_price"] == 100
    assert plan["stop_loss"] == 97
    assert plan["take_profit"] == 106
    assert any(
        gate["name"] == "entry_trigger" and gate["passed"] is False
        for gate in plan["gates"]
    )
