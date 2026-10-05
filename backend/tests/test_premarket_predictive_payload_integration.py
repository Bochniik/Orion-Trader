from datetime import datetime, timezone

import pandas as pd

from app.services import premarket_data_adapter as adapter_module
from app.services.premarket_data_adapter import PremarketDataAdapter


class FakeMarket:
    def get_price_history(self, symbol, period="1mo", interval="1d"):
        return pd.DataFrame()


def rows(start_hour=11, count=12, base=100.0):
    result = []
    for i in range(count):
        result.append({
            "t": f"2026-09-04T{start_hour:02d}:{i:02d}:00Z",
            "o": base + i * 0.1,
            "h": base + 0.2 + i * 0.1,
            "l": base - 0.1 + i * 0.1,
            "c": base + 0.1 + i * 0.1,
            "v": 10000 + i * 1000,
        })
    return result


class FakeSipBroker:
    def premarket_bars(self, user_id, symbols, **kwargs):
        return {"bars": {symbols[0]: []}, "limitations": []}

    def delayed_premarket_bars(self, user_id, symbols, **kwargs):
        symbol = symbols[0]
        return {
            "bars": {symbol: rows()},
            "provider": "alpaca",
            "feed": "sip",
            "delayed": True,
            "as_of": "2026-09-04T11:11:00+00:00",
            "limitations": [],
        }

    def premarket_snapshot_fallback(self, user_id, symbols, **kwargs):
        return {"symbols": {}, "warnings": []}


class FakeIexAndSipBroker:
    def premarket_bars(self, user_id, symbols, **kwargs):
        symbol = symbols[0]
        return {
            "bars": {symbol: rows(base=101.0)},
            "provider": "alpaca",
            "feed": "iex",
            "delayed": False,
            "as_of": "2026-09-04T11:11:30+00:00",
            "limitations": [],
        }

    def delayed_premarket_bars(self, user_id, symbols, **kwargs):
        symbol = symbols[0]
        return {
            "bars": {symbol: rows(base=100.0)},
            "provider": "alpaca",
            "feed": "sip",
            "delayed": True,
            "safe_delay_seconds": 960,
            "as_of": "2026-09-04T11:11:00+00:00",
            "limitations": [],
        }

    def premarket_snapshot_fallback(self, user_id, symbols, **kwargs):
        return {"symbols": {}, "warnings": []}


class FakeIexOnlyBroker:
    def premarket_bars(self, user_id, symbols, **kwargs):
        symbol = symbols[0]
        return {
            "bars": {symbol: rows(base=101.0)},
            "provider": "alpaca",
            "feed": "iex",
            "limitations": [],
        }

    def delayed_premarket_bars(self, user_id, symbols, **kwargs):
        return {
            "bars": {symbols[0]: []},
            "provider": "alpaca",
            "feed": "sip",
            "available": False,
            "limitations": ["SIP history unavailable in test"],
        }

    def premarket_snapshot_fallback(self, user_id, symbols, **kwargs):
        return {"symbols": {}, "warnings": []}


def test_sip_payload_attaches_hierarchical_outlook(monkeypatch):
    captured = {}

    def fake_predict(frame, *, previous_close, feed, as_of, model_path=None):
        captured["feed"] = feed
        captured["previous_close"] = previous_close
        captured["as_of"] = as_of
        captured["last_index"] = frame.index[-1]
        return {
            "available": True,
            "actionable": True,
            "model_version": "premarket_predictive_v3_hierarchical",
            "reason": None,
            "signals": {
                "open_5m": {
                    "actionable": True,
                    "direction": "UP",
                    "edge_probability": 0.62,
                    "direction_confidence": 0.58,
                }
            },
        }

    monkeypatch.setattr(adapter_module, "predict_gated_hierarchical_outlook", fake_predict)

    result = PremarketDataAdapter(FakeSipBroker(), FakeMarket()).build(
        "demo",
        "NVDA",
        now=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        previous_close_override=99.5,
    )

    assert result["feed"] == "sip"
    assert result["predictive_feed"] == "sip"
    assert result["predictive_outlook"]["actionable"] is True
    assert result["predictive_outlook"]["signals"]["open_5m"]["direction"] == "UP"
    assert captured["feed"] == "sip"
    assert captured["previous_close"] == result["previous_close"]
    assert captured["as_of"] == captured["last_index"]


def test_live_iex_context_uses_causal_sip_frame_for_validated_prediction(monkeypatch):
    captured = {}

    def fake_predict(frame, *, previous_close, feed, as_of, model_path=None):
        captured["feed"] = feed
        captured["first_open"] = float(frame.iloc[0]["Open"])
        captured["as_of"] = as_of
        return {
            "available": True,
            "actionable": False,
            "model_version": "premarket_predictive_v3_hierarchical",
            "reason": None,
            "signals": {
                "open_5m": {
                    "actionable": False,
                    "direction": "NO_EDGE",
                    "edge_probability": 0.51,
                    "direction_confidence": 0.61,
                    "up_given_edge": 0.61,
                    "down_given_edge": 0.39,
                }
            },
        }

    monkeypatch.setattr(adapter_module, "predict_gated_hierarchical_outlook", fake_predict)

    result = PremarketDataAdapter(FakeIexAndSipBroker(), FakeMarket()).build(
        "demo",
        "NVDA",
        now=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        previous_close_override=99.5,
    )

    # Descriptive setup uses fresher IEX bars.
    assert result["feed"] == "iex"
    assert result["data_mode"] == "iex_minute_history"
    assert result["premarket_open"] == 101.0

    # Validated model input stays on the SIP distribution it was trained on.
    assert result["predictive_feed"] == "sip"
    assert result["predictive_delayed"] is True
    assert result["predictive_bar_count"] == 12
    assert captured["feed"] == "sip"
    assert captured["first_open"] == 100.0
    assert captured["as_of"].isoformat() == result["predictive_as_of"]
    assert result["predictive_outlook"]["available"] is True


def test_iex_without_sip_keeps_setup_but_fails_closed_for_prediction(monkeypatch):
    calls = []

    def fake_predict(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("predictor must not receive IEX as a SIP-trained model input")

    monkeypatch.setattr(adapter_module, "predict_gated_hierarchical_outlook", fake_predict)

    result = PremarketDataAdapter(FakeIexOnlyBroker(), FakeMarket()).build(
        "demo",
        "NVDA",
        now=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        previous_close_override=99.5,
    )

    assert result["feed"] == "iex"
    assert result["full_intraday_history"] is True
    assert result["premarket_score"] is not None
    assert result["predictive_feed"] is None
    assert result["predictive_outlook"]["available"] is False
    assert result["predictive_outlook"]["reason"] == "sip_prediction_history_unavailable"
    assert calls == []
