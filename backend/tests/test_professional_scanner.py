"""Deterministic directional setup and horizon contracts; no provider calls."""
from copy import deepcopy
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.services.professional_scanner import PROFILES, build_research_setup, feature_evidence

NOW = datetime(2026, 9, 3, 15, 30, tzinfo=timezone.utc)


def bars(horizon="day", side=1):
    if horizon == "day":
        index = pd.date_range(end=NOW, periods=250, freq="min")
    else:
        index = pd.date_range(end="2026-09-02T20:00:00Z", periods=250, freq="B")
    # Gentle trend with a tight last-20-bar structure and strengthening last bar.
    close = 100 + side * (np.arange(250) * .015 + .05 * np.sin(np.arange(250) / 3))
    close[-1] = close[-2] + side * .15
    return pd.DataFrame({"Open": close - side * .02, "High": close + .12, "Low": close - .12,
                         "Close": close, "Volume": [1_000_000.] * 249 + [2_000_000.]}, index=index)


def screen(frame):
    return {"price": float(frame.Close.iloc[-1]), "data_timestamp": NOW.isoformat(), "quote_timestamp": NOW.isoformat(),
            "history_as_of": "2026-09-02T20:00:00Z", "history_sessions": 20, "provider": "alpaca",
            "average_dollar_volume": 500_000_000., "dollar_volume": 100_000_000., "relative_volume": 2.,
            "spread_pct": .02, "liquidity_score": 95, "data_status": "valid"}


def setup(horizon="day", side=1, **kwargs):
    frame = bars(horizon, side)
    return build_research_setup("TEST", horizon, kwargs.pop("screen", screen(frame)), frame, frame,
                                now=NOW, **kwargs)


@pytest.mark.parametrize("horizon", PROFILES)
@pytest.mark.parametrize("side", [1, -1])
def test_three_horizons_both_directions_have_auditable_levels(horizon, side):
    result = setup(horizon, side)
    assert result["eligible"]
    assert result["direction"] == ("bullish" if side == 1 else "bearish")
    assert result["quality_score"] == pytest.approx(sum(result["score_audit"]["points"].values()), abs=.01)
    assert sum(PROFILES[horizon]["weights"].values()) == 100
    assert side * (result["target_1"] - result["reference_entry"]) > 0
    assert side * (result["target_2"] - result["target_1"]) > 0
    assert side * (result["reference_entry"] - result["stop_loss"]) > 0
    assert result["confidence"] is None
    assert result["final_decision"] == "NO_TRADE" and not result["actionable"]
    assert {"macd_histogram", "rsi", "atr", "vwap", "support", "resistance", "trend_strength", "consolidation_ratio"} <= result["feature_snapshot"].keys()


def test_existing_5m_model_is_separate_from_60m_plan_and_never_reused_for_swing():
    model = {"expected_horizon": "5m", "probability_up": .72, "probability_down": .18,
             "probability_neutral": .1, "model_id": "fitted-fixture"}
    before = deepcopy(model)
    result = setup(model_results=[model])
    assert result["confidence"] == 72
    assert result["confidence_horizon"] == "5m"
    assert result["holding_horizon"] == {"value": 60, "unit": "minutes"}
    assert model == before
    assert setup("swing", model_results=[model])["confidence"] is None


@pytest.mark.parametrize("field,value,reason", [("spread_pct", None, "missing_stale_or_wide_spread"),
    ("spread_pct", .5, "missing_stale_or_wide_spread"), ("average_dollar_volume", 1000, "below_minimum_average_dollar_volume"),
    ("data_timestamp", "2020-01-01T00:00:00Z", "snapshot_stale")])
def test_fail_closed_input_gates(field, value, reason):
    s = screen(bars())
    s[field] = value
    result = setup(screen=s)
    assert not result["eligible"] and reason in result["reasons"]


def test_future_rows_cannot_change_features():
    frame = bars()
    baseline, regime = feature_evidence(frame, "day", frame, NOW)
    future = frame.tail(1).copy()
    future.index += pd.Timedelta(days=1)
    future[["Open", "High", "Low", "Close"]] *= 10
    extended = pd.concat([frame, future])
    observed, second_regime = feature_evidence(extended, "day", extended, NOW)
    assert observed == baseline and regime == second_regime


def test_conflicting_or_flat_market_is_neutral_not_forced_prediction():
    frame = bars()
    frame[["Open", "Close"]] = 100.
    frame["High"], frame["Low"] = 100.1, 99.9
    result = build_research_setup("FLAT", "day", screen(frame), frame, frame, now=NOW)
    assert not result["eligible"] and result["direction"] == "neutral"


def test_model_disagreement_blocks_quality_candidate():
    result = setup(model_results=[{"expected_horizon": "5m", "probability_up": .2, "probability_down": .7, "probability_neutral": .1}])
    assert not result["eligible"]
    assert "weak_or_contradictory_5m_model" in result["reasons"]


def test_missing_benchmark_and_short_history_do_not_fabricate_regime():
    frame = bars()
    result = build_research_setup("TEST", "day", screen(frame), frame, None, now=NOW)
    assert not result["eligible"] and result["confidence"] is None
    result = build_research_setup("TEST", "long_term", screen(frame), frame.tail(20), frame, now=NOW)
    assert result["reasons"] == ["insufficient_long_term_history"]


def test_delayed_features_cannot_show_expired_five_minute_probability():
    frame = bars()
    frame.index -= pd.Timedelta(minutes=6)
    model = {"expected_horizon": "5m", "probability_up": .72, "probability_down": .18, "probability_neutral": .1}
    result = build_research_setup("TEST", "day", screen(frame), frame, frame, now=NOW, model_results=[model])
    assert result["confidence"] is None
    assert result["confidence_target_timestamp"] is None
