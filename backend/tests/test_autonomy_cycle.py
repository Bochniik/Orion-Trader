from app.api import routes


def broker_account():
    return {"equity": "100000", "cash": "90000", "buying_power": "400000", "last_equity": "100000", "status": "ACTIVE", "trading_blocked": False}


def scan_result():
    candidate = {"symbol": "AAPL", "price": 100, "bid": 99.9, "ask": 100.1, "spread_percent": .2, "daily_volume": 2_000_000, "change_percent": 1, "held": False}
    return {"universe_size": 8000, "screened_symbols": 25, "qualified_count": 1, "candidates": [candidate], "partial_failure": False, "errors": []}


def configure_cycle_mocks(monkeypatch):
    monkeypatch.setattr(routes.alpaca_broker, "status", lambda user_id: {"connected": True, "order_submission_enabled": True})
    monkeypatch.setattr(routes.alpaca_broker, "account", lambda user_id: broker_account())
    monkeypatch.setattr(routes.alpaca_broker, "positions", lambda user_id: [])
    monkeypatch.setattr(routes.alpaca_broker, "clock", lambda user_id: {"is_open": True})
    monkeypatch.setattr(routes.market_scanner, "scan", lambda *args: scan_result())
    monkeypatch.setattr(routes, "build_orion_context", lambda symbol: {"ticker": symbol, "context_meta": {"partial_failure": False}})
    monkeypatch.setattr(routes, "evaluate_autonomous_candidate", lambda candidate, context, portfolio, settings: {"symbol": candidate["symbol"], "action": "BUY", "confidence": 90, "thesis": "Qualified trend", "invalidation_price": 95, "risks": []})


def test_shadow_cycle_records_proposal_without_order(tmp_path, monkeypatch):
    configure_cycle_mocks(monkeypatch)
    monkeypatch.setattr(routes.alpaca_broker, "submit_autonomous_order", lambda *args: (_ for _ in ()).throw(AssertionError("shadow must not submit")))
    result = routes.run_autonomy_cycle("shadow-user", tmp_path / "shadow.db", "shadow")
    assert result["scan"]["universe_size"] == 8000
    assert result["proposals"][0]["status"] == "shadow"


def test_autonomous_cycle_submits_only_risk_sized_limit_order(tmp_path, monkeypatch):
    configure_cycle_mocks(monkeypatch)
    monkeypatch.setenv("ORION_AUTONOMY_ENABLED", "true")
    submitted = []
    monkeypatch.setattr(routes.alpaca_broker, "submit_autonomous_order", lambda user_id, symbol, qty, side, limit_price: submitted.append({"symbol": symbol, "qty": qty, "side": side, "limit_price": limit_price}) or {"id": "paper-order-1"})
    result = routes.run_autonomy_cycle("auto-user", tmp_path / "auto.db", "autonomous")
    assert result["proposals"][0]["status"] == "submitted"
    assert submitted == [{"symbol": "AAPL", "qty": 20, "side": "buy", "limit_price": 100.3}]


def test_hold_cycle_records_neutral_observation_instead_of_risk_rejection(tmp_path, monkeypatch):
    configure_cycle_mocks(monkeypatch)
    monkeypatch.setattr(routes, "evaluate_autonomous_candidate", lambda candidate, context, portfolio, settings: {"symbol": candidate["symbol"], "action": "HOLD", "confidence": 82, "thesis": "Wait for confirmation", "invalidation_price": None, "risks": []})

    result = routes.run_autonomy_cycle("hold-user", tmp_path / "hold.db", "shadow")

    assert result["proposals"][0]["status"] == "observed_hold"
    assert result["proposals"][0]["risk"]["classification"] == "hold"
