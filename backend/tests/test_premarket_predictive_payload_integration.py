from datetime import datetime, timezone

import pandas as pd

from app.services import premarket_data_adapter as adapter_module
from app.services.premarket_data_adapter import PremarketDataAdapter


class FakeMarket:
    def get_price_history(self, symbol, period="1mo", interval="1d"):
        return pd.DataFrame()


class FakeSipBroker:
    def premarket_bars(self, user_id, symbols, **kwargs):
        return {"bars": {symbols[0]: []}, "limitations": []}

    def delayed_premarket_bars(self, user_id, symbols, **kwargs):
        symbol = symbols[0]
        rows = []
        for i in range(12):
            rows.append({
                "t": f"2026-09-04T11:{i:02d}:00Z",
                "o": 100.0 + i * 0.1,
                "h": 100.2 + i * 0.1,
                "l": 99.9 + i * 0.1,
                "c": 100.1 + i * 0.1,
                "v": 10000 + i * 1000,
            })
        return {
            "bars": {symbol: rows},
            "provider": "alpaca",
            "feed": "sip",
            "delayed": True,
            "as_of": "2026-09-04T11:11:00+00:00",
            "limitations": [],
        }

    def premarket_snapshot_fallback(self, user_id, symbols, **kwargs):
        return {"symbols": {}, "warnings": []}


class FakeIexBroker:
    def premarket_bars(self, user_id, symbols, **kwargs):
        symbol = symbols[0]
        rows = []
        for i in range(12):
            rows.append({
                "t": f"2026-09-04T11:{i:02d}:00Z",
                "o": 100.0 + i * 0.1,
                "h": 100.2 + i * 0.1,
                "l": 99.9 + i * 0.1,
                "c": 100.1 + i * 0.1,
                "v": 10000 + i * 1000,
            })
        return {
            "bars": {symbol: rows},
            "provider": "alpaca",
            "feed": "iex",
            "limitations": [],
        }

    def delayed_premarket_bars(self, user_id, symbols, **kwargs):
        raise AssertionError("SIP fallback should not be used when IEX history is sufficient")

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
    assert result["predictive_outlook"]["actionable"] is True
    assert result["predictive_outlook"]["signals"]["open_5m"]["direction"] == "UP"
    assert captured["feed"] == "sip"
    assert captured["previous_close"] == result["previous_close"]
    assert captured["as_of"] == captured["last_index"]


def test_iex_payload_exposes_non_actionable_feed_mismatch(monkeypatch):
    def fake_predict(frame, *, previous_close, feed, as_of, model_path=None):
        assert feed == "iex"
        return {
            "available": False,
            "actionable": False,
            "model_version": "premarket_predictive_v3_hierarchical",
            "reason": "training_feed_mismatch_requires_sip",
            "signals": {},
        }

    monkeypatch.setattr(adapter_module, "predict_gated_hierarchical_outlook", fake_predict)

    result = PremarketDataAdapter(FakeIexBroker(), FakeMarket()).build(
        "demo",
        "NVDA",
        now=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        previous_close_override=99.5,
    )

    assert result["feed"] == "iex"
    assert result["predictive_outlook"]["actionable"] is False
    assert result["predictive_outlook"]["reason"] == "training_feed_mismatch_requires_sip"
