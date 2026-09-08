import numpy as np
import pandas as pd

from app.services.strategy_intelligence import analyze_strategy_set


def price_frame(prices, volume=1_000_000):
    values = np.asarray(prices, dtype=float)
    index = pd.date_range("2025-01-01", periods=len(values), freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "Open": values - 0.2,
            "High": values + 1,
            "Low": np.maximum(0.01, values - 1),
            "Close": values,
            "Volume": volume,
        },
        index=index,
    )


def strategy(result, strategy_id):
    return next(item for item in result["strategies"] if item["id"] == strategy_id)


def supportive_market(length=260):
    return price_frame(np.linspace(100, 130, length))


def test_recent_golden_cross_requires_confirmation_and_is_not_probability():
    daily = price_frame([100] * 205 + [80] * 50 + [400] * 5)
    result = analyze_strategy_set(
        "AAPL",
        daily,
        market_history=supportive_market(),
        quote={"price": 400},
    )
    golden = strategy(result, "golden_cross")

    assert golden["status"] == "triggered"
    assert golden["score"] == 100
    assert golden["score_meaning"] == "Rule completion, not probability of profit"
    assert golden["evidence_snapshot"]["recent_cross"] is True
    assert golden["levels"]["risk_reward"] == 2
    assert result["top_setup"]["not_an_order"] is True
    assert any("not probability" in warning for warning in result["safety"])


def test_recent_death_cross_is_a_defensive_warning_not_an_automatic_short():
    daily = price_frame([100] * 205 + [105] * 50 + [1] * 5)
    result = analyze_strategy_set(
        "RISK",
        daily,
        market_history=supportive_market(),
        quote={"price": 1},
    )
    death = strategy(result, "death_cross")

    assert death["status"] == "defensive_trigger"
    assert death["bias"] == "defensive"
    assert "does not convert it into an automatic short" in death["summary"]
    assert death["levels"]["entry"] is None


def test_unaligned_strategies_do_not_publish_actionable_price_levels():
    daily = price_frame(np.linspace(130, 90, 260))
    result = analyze_strategy_set("WEAK", daily, market_history=supportive_market())

    for item in result["strategies"]:
        if item["status"] not in {"triggered", "aligned", "forming"}:
            assert item["levels"] == {
                "entry": None,
                "stop": None,
                "target": None,
                "risk_reward": None,
            }


def test_pairs_output_is_explicitly_only_a_divergence_screen():
    x = np.arange(260)
    peer_prices = 100 + np.cumsum(0.2 + np.sin(x / 3) * 0.4)
    primary_prices = peer_prices * 1.05
    primary_prices[-20:] *= np.exp(np.linspace(0, 0.08, 20))
    result = analyze_strategy_set(
        "AAA",
        price_frame(primary_prices),
        market_history=supportive_market(),
        peer_ticker="BBB",
        peer_history=price_frame(peer_prices),
    )
    pairs = strategy(result, "pairs_trading")

    assert pairs["status"] == "divergence_screen"
    assert abs(pairs["evidence_snapshot"]["spread_z_score"]) >= 2
    assert pairs["evidence_snapshot"]["return_correlation_60"] >= 0.7
    assert pairs["evidence_snapshot"]["cointegration_validated"] is False
    assert any("do not prove" in note for note in pairs["risk_notes"])


def test_catalyst_orb_uses_latest_session_range_vwap_and_relative_volume():
    daily_prices = [100] * 259 + [106]
    daily = price_frame(daily_prices)
    prior_index = pd.date_range("2026-01-05 14:30", periods=6, freq="5min", tz="UTC")
    current_index = pd.date_range("2026-01-06 14:30", periods=6, freq="5min", tz="UTC")
    intraday = pd.DataFrame(
        {
            "Open": [100] * 6 + [104, 104.5, 105, 105.3, 105.6, 105.9],
            "High": [100.4] * 6 + [104.8, 105, 105.4, 105.7, 106, 106.5],
            "Low": [99.8] * 6 + [103.8, 104.2, 104.7, 105, 105.3, 105.7],
            "Close": [100] * 6 + [104.5, 104.8, 105.2, 105.5, 105.8, 106.3],
            "Volume": [100] * 6 + [400] * 6,
        },
        index=prior_index.append(current_index),
    )
    result = analyze_strategy_set(
        "NEWS",
        daily,
        intraday_history=intraday,
        market_history=supportive_market(),
        news={"ticker": "NEWS", "news": [{"title": "NEWS raises guidance after earnings"}]},
        quote={"price": 106.3},
    )
    orb = strategy(result, "catalyst_orb")

    assert orb["status"] == "triggered"
    assert orb["evidence_snapshot"]["gap_percent"] == 4
    assert orb["evidence_snapshot"]["relative_volume"] == 4
    assert orb["evidence_snapshot"]["vwap"] is not None
    assert orb["levels"]["risk_reward"] == 2


def test_all_playbooks_fail_closed_when_200_sma_history_is_missing():
    result = analyze_strategy_set("SHORT", price_frame(np.linspace(100, 120, 100)))

    assert result["data_quality"]["sufficient"] is False
    assert result["top_setup"] is None
    assert len(result["strategies"]) == 9
    assert all(item["status"] == "data_insufficient" for item in result["strategies"])
    assert all(item["score"] is None for item in result["strategies"])
