"""Existing-provider/model integration with deterministic, network-free clients."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import numpy as np
import pandas as pd
import pytest

from app.services import staged_scanner_adapters as adapters
from app.services.liquidity_engine import build_liquidity_observation
from app.services.predictive_features import MODEL_FEATURES
from app.services.predictive_models import predict_probabilities
from app.services.staged_market_scanner import ScannerConfig, StagedMarketScanner


NOW = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)


def daily_history():
    index = pd.date_range("2026-07-27", "2026-08-24", freq="B", tz="UTC")
    return pd.DataFrame({"Close": np.linspace(98, 100, len(index)), "Volume": 5_000_000.0}, index=index)


def minute_history():
    index = pd.date_range("2026-08-25T13:30:00Z", periods=120, freq="min")
    close = 100 * np.exp(np.arange(len(index)) * .003)
    return pd.DataFrame({"Open": close - .01, "High": close + .05, "Low": close - .05,
                         "Close": close, "Volume": 100_000.0}, index=index)


def snapshot():
    return {"latestTrade": {"p": 104, "t": "2026-08-25T15:29:55Z"},
            "latestQuote": {"bp": 103.99, "ap": 104.01, "bs": 100, "as": 100, "t": "2026-08-25T15:29:56Z"},
            "dailyBar": {"c": 104, "v": 5_000_000, "n": 100_000, "t": "2026-08-25T04:00:00Z"},
            "prevDailyBar": {"c": 100}}


class Broker:
    def __init__(self, symbols=("MOVE", "ILLIQ")):
        self.symbols = symbols
        self.data = {s: snapshot() for s in symbols}
        self.snapshot_calls = []

    def assets(self, user_id):
        return [{"symbol": s, "name": s + " Corporation", "tradable": True, "status": "active"} for s in self.symbols]

    def snapshots(self, user_id, tickers):
        self.snapshot_calls.append(list(tickers))
        return {s: deepcopy(self.data[s]) for s in tickers if s in self.data}

    def clock(self, user_id):
        return {"is_open": True}


class Market:
    def __init__(self):
        self.daily, self.minute = {}, {}
        self.daily_calls, self.minute_calls = [], []

    def get_liquidity_histories(self, symbols, *, period):
        assert period == "1mo"
        self.daily_calls.append(list(symbols))
        return {"histories": {s: self.daily.get(s, daily_history()).copy() for s in symbols}, "errors": []}

    def get_intraday_histories(self, symbols, *, period, interval):
        assert period == "5d" and interval == "1m"
        assert len(symbols) <= 50
        self.minute_calls.append(list(symbols))
        return {"histories": {s: self.minute.get(s, minute_history()).copy() for s in symbols}, "errors": []}


def fitted_fixture():
    """Hand-specified TEST weights exercise real inference; no training occurs."""
    n = len(MODEL_FEATURES)
    horizon = {
        "probabilities_available": True, "reliable": False, "status": "experimental_unvalidated",
        "medians": [0.0] * n, "scales": [1.0] * n,
        "models": {"logistic_regression": {"weights": np.zeros((n, 3)).tolist(), "bias": np.log([.1, .2, .7]).tolist()},
                   "gradient_boosted_stumps": {"base": np.log([.2, .2, .6]).tolist(), "learning_rate": .12, "stumps": []}},
        "calibration": {"temperature": 1.25},
        "holdout": {"expected_calibration_error": .15},
        "conditional_return_statistics": {"UP": {"mean": .01}, "DOWN": {"mean": -.01}, "NEUTRAL": {"mean": 0}},
    }
    return {"model_id": "synthetic-fitted-fixture", "artifact": {"version": "fixture-v1", "horizons": {"1m": deepcopy(horizon), "5m": horizon}}}


def test_reuses_existing_universe_snapshots_and_liquidity_math():
    market, broker = Market(), Broker()
    source = adapters.ExistingMarketScannerSource(market, broker, "test-user")
    universe = source.stock_universe()
    assert universe["tickers"] == ["ILLIQ", "MOVE"]
    assert universe["complete_us_universe"] is False
    loaded = source.load_screening_batch(["MOVE"], now=NOW)
    row = loaded["rows"]["MOVE"]
    expected = build_liquidity_observation("MOVE", snapshot(), daily_history(), now=NOW)
    assert row["liquidity_score"] == expected["liquidity_score"]
    assert row["average_dollar_volume"] == expected["metrics"]["average_dollar_volume_20d"]
    assert row["relative_volume"] == expected["metrics"]["relative_volume_rate"]
    assert row["company_name"] == "MOVE Corporation"
    assert row["dollar_volume"] == 104 * 5_000_000
    assert row["intraday_return"] == pytest.approx(.04)
    assert row["provider"] == "alpaca" and row["feed"] == "iex"
    assert broker.snapshot_calls == market.daily_calls == [["MOVE"]]


def test_fresh_quote_cannot_disguise_an_old_trade_price():
    market, broker = Market(), Broker(("OLD",))
    broker.data["OLD"]["latestTrade"]["t"] = "2026-08-25T15:00:00Z"
    result = adapters.scan_with_existing_services(market_data=market, alpaca_broker=broker,
                                                  user_id="test", model=fitted_fixture(), now=NOW)
    assert result["candidates"] == []
    assert result["exclusion_counts"]["data_quality:snapshot_stale"] == 1
    assert market.minute_calls == []


def test_stale_optional_spread_is_unavailable_not_invented():
    market, broker = Market(), Broker(("MOVE",))
    broker.data["MOVE"]["latestQuote"]["t"] = "2026-08-25T15:00:00Z"
    source = adapters.ExistingMarketScannerSource(market, broker, "test")
    row = source.load_screening_batch(["MOVE"], now=NOW)["rows"]["MOVE"]
    assert row["spread_pct"] is None
    assert row["liquidity_row"]["metrics"]["spread_percent"] is None
    assert row["quote_timestamp"] == "2026-08-25T15:00:00Z"


def test_previous_session_volume_and_short_history_do_not_pass_screening():
    market, broker = Market(), Broker(("OLD", "SHORT"))
    broker.data["OLD"]["dailyBar"]["t"] = "2026-08-24T04:00:00Z"
    market.daily["SHORT"] = daily_history().tail(9)
    result = adapters.scan_with_existing_services(market_data=market, alpaca_broker=broker,
                                                  user_id="test", model=fitted_fixture(), now=NOW)
    assert result["candidates"] == []
    assert result["exclusion_counts"]["data_quality:provider_invalid_data"] == 1
    assert result["exclusion_counts"]["data_quality:insufficient_daily_history"] == 1
    assert market.minute_calls == []


def test_incomplete_daily_and_minute_bars_cannot_leak_into_scores():
    market, broker = Market(), Broker(("MOVE",))
    source = adapters.ExistingMarketScannerSource(market, broker, "test")
    base_screen = source.load_screening_batch(["MOVE"], now=NOW)["rows"]["MOVE"]
    base_feature = source.load_feature_snapshots(["MOVE"], now=NOW)["rows"]["MOVE"]
    contaminated_day = daily_history()
    contaminated_day.loc[pd.Timestamp("2026-08-25T00:00:00Z")] = [99_999, 99_999_999_999]
    market.daily["MOVE"] = contaminated_day
    future = minute_history()
    future.loc[pd.Timestamp("2026-08-25T15:30:00Z")] = [9999, 9999, 9999, 9999, 9999]
    market.minute["MOVE"] = future
    screen = source.load_screening_batch(["MOVE"], now=NOW)["rows"]["MOVE"]
    feature = source.load_feature_snapshots(["MOVE"], now=NOW)["rows"]["MOVE"]
    assert screen["average_dollar_volume"] == base_screen["average_dollar_volume"]
    assert feature["feature_snapshot"] == base_feature["feature_snapshot"]
    assert feature["provenance"]["raw_timestamp"] == "2026-08-25T15:29:00+00:00"
    assert feature["provenance"]["canonical_timestamp"] == "2026-08-25T15:30:00+00:00"
    assert feature["history_bars"] == 120


@pytest.mark.parametrize("issue", ["negative_volume", "duplicate_timestamp", "missing_timezone", "impossible_high"])
def test_invalid_minute_candles_are_not_scored(issue):
    market, broker = Market(), Broker(("MOVE",))
    frame = minute_history()
    if issue == "negative_volume":
        frame.iloc[-1, frame.columns.get_loc("Volume")] = -1
    elif issue == "duplicate_timestamp":
        frame = pd.concat([frame, frame.tail(1)])
    elif issue == "missing_timezone":
        frame.index = frame.index.tz_localize(None)
    else:
        frame.iloc[-1, frame.columns.get_loc("High")] = 1
    market.minute["MOVE"] = frame
    out = adapters.ExistingMarketScannerSource(market, broker, "test").load_feature_snapshots(["MOVE"], now=NOW)
    assert "MOVE" not in out["rows"]
    assert out["errors"]


def test_transport_cap_does_not_silently_drop_activity_finalists_or_duplicate_spy():
    market, broker = Market(), Broker()
    source = adapters.ExistingMarketScannerSource(market, broker, "test")
    symbols = [f"S{i:03d}" for i in range(100)]
    out = source.load_feature_snapshots(symbols, now=NOW)
    assert set(out["rows"]) == set(symbols)
    assert [len(group) for group in market.minute_calls] == [50, 50, 1]
    all_requested = [s for group in market.minute_calls for s in group]
    assert len(all_requested) == len(set(all_requested)) == 101
    assert all_requested.count("SPY") == 1


def test_real_existing_inference_preserves_calibration_and_no_trade_without_training(monkeypatch):
    market, broker = Market(), Broker(("MOVE", "ILLIQ"))
    market.daily["ILLIQ"] = daily_history().assign(Volume=100)
    model = fitted_fixture()
    before = deepcopy(model)
    calls = []
    original = adapters.build_live_prediction

    def recording(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(adapters, "build_live_prediction", recording)
    result = adapters.scan_with_existing_services(market_data=market, alpaca_broker=broker,
                                                  user_id="test", model=model, now=NOW)
    assert calls == ["MOVE"]
    assert market.minute_calls == [["MOVE", "SPY"]]
    row = result["candidates"][0]
    actual = predict_probabilities(model["artifact"]["horizons"]["5m"], {"features": {}})
    assert row["probability_up"] == actual["P_UP"]
    assert row["probability_down"] == actual["P_DOWN"]
    assert row["raw_probabilities"] == actual["raw_probabilities"]
    assert row["calibration_temperature"] == 1.25
    assert row["model_direction"] == "UP"
    assert row["final_decision"] == "NO_TRADE" and row["actionable"] is False
    assert row["model_status"] == "experimental_unvalidated"
    assert any("out-of-sample" in w for w in row["warnings"])
    assert row["delayed"] is True and row["feature_provider"] == "yahoo"
    assert row["model_id"] == "synthetic-fitted-fixture"
    assert model == before
    json.dumps(result, allow_nan=False)


def test_missing_models_and_30s_horizon_never_invent_probabilities(monkeypatch):
    market, broker = Market(), Broker(("MOVE",))
    source = adapters.ExistingMarketScannerSource(market, broker, "test")
    ctx = source.load_feature_snapshots(["MOVE"], now=NOW)["rows"]["MOVE"]
    screen = source.load_screening_batch(["MOVE"], now=NOW)["rows"]["MOVE"]

    def forbidden(*args, **kwargs):
        pytest.fail("Unavailable horizons must not invoke model inference")

    monkeypatch.setattr(adapters, "build_live_prediction", forbidden)
    absent = adapters.ExistingOrionScannerAnalyzer(None)("MOVE", screen, ctx, ("5m",), now=NOW)
    assert absent["results"] == [] and absent["model_calls"] == 0
    assert "No existing fitted" in absent["unavailable"][0]["reason"]
    model = fitted_fixture()
    model["artifact"]["horizons"]["30s"] = model["artifact"]["horizons"]["5m"]
    unsupported = adapters.ExistingOrionScannerAnalyzer(model)("MOVE", screen, ctx, ("30s",), now=NOW)
    assert unsupported["results"] == [] and unsupported["model_calls"] == 0
    assert "Sub-minute evidence is unavailable" in unsupported["unavailable"][0]["reason"]


def test_stale_benchmark_is_missing_evidence_not_current_confirmation():
    market, broker = Market(), Broker(("MOVE",))
    market.minute["SPY"] = minute_history().iloc[:-10]
    result = adapters.ExistingMarketScannerSource(market, broker, "test").load_feature_snapshots(["MOVE"], now=NOW)
    snapshot = result["rows"]["MOVE"]["feature_snapshot"]
    assert snapshot["features"]["index_momentum"] is None
    assert snapshot["features"]["relative_strength_market"] is None
    assert snapshot["feature_provenance"]["index_momentum"]["status"] == "unavailable"


def test_no_model_is_an_explicit_empty_scanner_state():
    result = adapters.scan_with_existing_services(market_data=Market(), alpaca_broker=Broker(("MOVE",)),
                                                  user_id="test", model=None, now=NOW)
    assert result["status"] == "no_high_quality_candidates"
    assert result["stage_counts"]["model_evaluations"] == 0
    assert result["unavailable_analyses"][0]["horizon"] == "5m"


def test_minute_provider_failure_remains_partial_and_does_not_reach_model():
    market, broker = Market(), Broker(("MOVE",))

    def fail(*args, **kwargs):
        raise TimeoutError("synthetic provider timeout")

    market.get_intraday_histories = fail
    result = adapters.scan_with_existing_services(market_data=market, alpaca_broker=broker,
                                                  user_id="test", model=fitted_fixture(), now=NOW)
    assert result["candidates"] == []
    assert result["partial_failure"] is True
    assert result["stage_counts"]["model_evaluations"] == 0
