import pytest
import pandas as pd
import inspect
from starlette.testclient import TestClient

from app.api import routes
from app.main import app
from app.services.memory_store import OrionMemoryStore
from app.services.paper_trader import PaperTrader
from app.services.watchlist import Watchlist
from app.services.context_cache import MarketContextCache
from app.services.strategy_store import StrategyStore
from app.services.autonomy_store import AutonomyStore
from app.services.predictive_store import PredictiveIntelligenceStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    database = tmp_path / "orion.db"
    monkeypatch.setattr(routes, "memory", OrionMemoryStore(database))
    monkeypatch.setattr(routes, "paper", PaperTrader(database_path=database))
    monkeypatch.setattr(routes, "watchlist", Watchlist(database, default_tickers=[]))
    monkeypatch.setattr(routes, "strategy_store", StrategyStore(database))
    return TestClient(app)


def test_memory_round_trip_is_visible_to_frontend(client):
    routes.memory.add_exchange("AAPL", "What changed?", "The trend improved.")

    response = client.get("/orion-ai/memory/aapl?limit=12")
    assert response.status_code == 200
    assert response.json()["history"][0]["question"] == "What changed?"
    assert response.json()["stats"]["exchange_count"] == 1

    cleared = client.delete("/orion-ai/memory/AAPL")
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] == 1


def test_portfolio_review_accepts_optional_body_and_saves_general_memory(
    client, monkeypatch
):
    monkeypatch.setattr(
        routes,
        "review_portfolio",
        lambda portfolio: {"question": "Review", "answer": "Looks balanced."},
    )

    response = client.post("/orion-ai/portfolio-review")
    assert response.status_code == 200
    assert routes.memory.get_stats("GENERAL")["exchange_count"] == 1


def test_analysis_route_matches_frontend_contract(client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "build_orion_context",
        lambda ticker: {
            "quote": {},
            "technical_analysis": {},
            "recent_news": [],
            "context_meta": {"partial_failure": False, "components": {}},
        },
    )
    monkeypatch.setattr(
        routes,
        "analyze_with_llm",
        lambda *args: {
            "symbol": "AAPL",
            "outlook": "Neutral",
            "confidence": 50,
            "summary": "Test",
            "reasons": [],
            "risks": [],
        },
    )

    assert client.get("/orion-ai/analysis/AAPL").status_code == 200


def test_health_supports_read_only_get(client):
    response = client.get("/orion-ai/portfolio-health")
    assert response.status_code == 200
    assert 0 <= response.json()["score"] <= 100


def test_application_health_is_network_free(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": "OrionTrader",
        "version": "2.4.0",
        "orion_ai_configured": False,
    }


def test_explosive_move_status_discloses_unvalidated_research_boundary(
    client, monkeypatch
):
    monkeypatch.setattr(routes.alpaca_broker, "status", lambda _user_id: {"connected": True})
    monkeypatch.setattr(routes.trading212_demo, "status", lambda _user_id: {"connected": False})
    monkeypatch.setattr(
        routes.sec_edgar,
        "status",
        lambda: {"configured": False, "source": "SEC EDGAR"},
    )

    response = client.get("/explosive-moves/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["market_feed"]["current_mode"] == "bounded_snapshot"
    assert payload["market_feed"]["stream_active"] is False
    assert payload["probability_model"]["status"] == "not_calibrated"
    assert payload["execution"] == "research_and_shadow_only"


def test_predictive_status_discloses_all_phases_and_fail_closed_model_state(
    client, monkeypatch
):
    monkeypatch.setattr(
        routes.alpaca_broker, "status", lambda _user_id: {"connected": True}
    )

    response = client.get("/predictive-intelligence/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["implemented_phase"] == 11
    assert payload["phases"]["liquidity_engine"] == "active"
    assert payload["phases"]["prediction_models"] == "active"
    assert payload["phases"]["prediction_laboratory"] == "active"
    assert payload["probabilities"] == "train_baseline_first"
    assert payload["llm_probability_calculation"] is False
    assert payload["automatic_order_execution"] is False


def test_liquidity_ranking_is_bounded_persisted_and_has_no_order_or_llm_path(
    client, monkeypatch, tmp_path
):
    database = tmp_path / "predictive.db"
    monkeypatch.setattr(routes, "autonomy_store", AutonomyStore(database))
    assets = [
        {"symbol": symbol, "tradable": True, "asset_class": "us_equity"}
        for symbol in ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "TSLA", "AMD", "AVGO", "NFLX"]
    ]
    history_index = pd.date_range("2026-07-01", periods=30, freq="B")
    histories = {
        symbol: pd.DataFrame(
            {"Close": [100 + index * 0.1 for index in range(30)], "Volume": [5_000_000] * 30},
            index=history_index,
        )
        for symbol in (asset["symbol"] for asset in assets)
    }
    snapshots = {
        symbol: {
            "latestTrade": {"p": 103, "t": "2026-08-25T15:30:00Z"},
            "latestQuote": {"bp": 102.99, "ap": 103.01, "t": "2026-08-25T15:30:00Z"},
            "dailyBar": {"c": 103, "v": 3_000_000, "n": 40_000, "t": "2026-08-25T15:30:00Z"},
        }
        for symbol in histories
    }
    monkeypatch.setattr(
        routes.alpaca_broker, "status", lambda _user_id: {"connected": True}
    )
    monkeypatch.setattr(routes.alpaca_broker, "assets", lambda _user_id: assets)
    monkeypatch.setattr(
        routes.alpaca_broker,
        "market_candidates",
        lambda _user_id, _limit: ([asset["symbol"] for asset in assets], []),
    )
    monkeypatch.setattr(
        routes.alpaca_broker,
        "snapshots",
        lambda _user_id, symbols: {symbol: snapshots[symbol] for symbol in symbols},
    )
    monkeypatch.setattr(
        routes.market,
        "get_liquidity_histories",
        lambda symbols, period: {
            "histories": {symbol: histories[symbol] for symbol in symbols},
            "errors": [],
        },
    )

    ranked = client.post(
        "/predictive-intelligence/liquidity/rankings",
        json={"candidate_count": 10, "history_period": "3mo"},
    )
    assert ranked.status_code == 200
    payload = ranked.json()
    assert payload["summary"]["ranked_securities"] == 10
    assert payload["discovery"]["screened_symbols"] == 10
    assert payload["prediction_status"]["probabilities"] is None
    assert payload["safety_boundary"].endswith("automatic execution path is used.")

    listed = client.get("/predictive-intelligence/liquidity/history?limit=10")
    assert listed.status_code == 200
    assert listed.json()["rankings"][0]["history_id"] == payload["history_id"]
    assert "rankings" not in listed.json()["rankings"][0]

    detail = client.get(
        f"/predictive-intelligence/liquidity/history/{payload['history_id']}"
    )
    assert detail.status_code == 200
    assert len(detail.json()["rankings"]) == 10

    route_source = inspect.getsource(routes.run_liquidity_ranking)
    assert "ask_orion" not in route_source
    assert "submit_" not in route_source

    deleted = client.delete("/predictive-intelligence/liquidity/history")
    assert deleted.json()["deleted"] == 1


def test_liquidity_ranking_requires_connected_research_data(client, monkeypatch):
    monkeypatch.setattr(
        routes.alpaca_broker, "status", lambda _user_id: {"connected": False}
    )

    response = client.post(
        "/predictive-intelligence/liquidity/rankings",
        json={"candidate_count": 10, "history_period": "3mo"},
    )

    assert response.status_code == 400
    assert "Connect Alpaca Paper" in response.json()["detail"]


def test_explosive_move_stream_routes_are_explicit_and_research_only(
    client, monkeypatch
):
    calls = []

    class FakeStreamManager:
        def status(self, user_id):
            return {
                "state": "connected", "running": True, "healthy": True,
                "feed": "iex", "symbols": ["AAPL", "MSFT"],
                "channels": {"market": {"state": "connected"}, "news": {"state": "connected"}},
            }

        def start(self, user_id, database_path, symbols, feed="iex", all_news=False):
            calls.append(("start", user_id, str(database_path), symbols, feed, all_news))
            return self.status(user_id)

        def update_symbols(self, user_id, symbols):
            calls.append(("update", user_id, symbols))
            return self.status(user_id)

        def event_page(self, user_id, after_sequence, limit, event_types):
            calls.append(("events", user_id, after_sequence, limit, event_types))
            return {"events": [], "next_sequence": 7, "reset_required": False}

        def stop(self, user_id):
            calls.append(("stop", user_id))
            return {**self.status(user_id), "state": "stopped", "running": False}

    monkeypatch.setattr(routes, "stream_manager", FakeStreamManager())

    started = client.post(
        "/explosive-moves/stream/start",
        json={"symbols": ["AAPL", "MSFT"], "feed": "iex", "all_news": False},
    )
    updated = client.put(
        "/explosive-moves/stream/subscriptions", json={"symbols": ["NVDA"]}
    )
    events = client.get(
        "/explosive-moves/stream/events?after_sequence=3&limit=20&types=news,bar"
    )
    stopped = client.post("/explosive-moves/stream/stop")

    assert started.status_code == 200
    assert started.json()["safety_boundary"].startswith("Research evidence only")
    assert updated.status_code == 200
    assert events.json()["next_sequence"] == 7
    assert stopped.json()["stream"]["running"] is False
    assert calls[0][0] == "start"
    assert calls[1] == ("update", "test-user", ["NVDA"])
    assert calls[2][4] == {"news", "bar"}
    assert calls[3] == ("stop", "test-user")


def test_explosive_move_stream_rejects_unknown_feed_before_network(client):
    response = client.post(
        "/explosive-moves/stream/start",
        json={"symbols": ["AAPL"], "feed": "crypto"},
    )

    assert response.status_code == 422


def test_alpaca_disconnect_stops_stream_before_credentials_are_removed(
    client, monkeypatch
):
    calls = []
    monkeypatch.setattr(routes.stream_manager, "stop", lambda user_id: calls.append(("stream", user_id)))
    monkeypatch.setattr(routes.agent_manager, "kill", lambda user_id: calls.append(("agent", user_id)))
    monkeypatch.setattr(routes.alpaca_broker, "cancel_autonomous_orders", lambda user_id: calls.append(("cancel", user_id)))
    monkeypatch.setattr(routes.alpaca_broker, "disconnect", lambda user_id: calls.append(("broker", user_id)))
    monkeypatch.setattr(routes.alpaca_broker, "status", lambda _user_id: {"connected": False})
    monkeypatch.setattr(routes.autonomy_store, "get_source", lambda: "local")
    monkeypatch.setattr(routes.autonomy_store, "add_event", lambda *_args, **_kwargs: None)

    response = client.post("/broker/alpaca/disconnect")

    assert response.status_code == 200
    assert calls[:2] == [("stream", "test-user"), ("agent", "test-user")]
    assert calls[-1] == ("broker", "test-user")


def test_extreme_move_replay_routes_persist_summary_and_full_audit(
    client, monkeypatch, tmp_path
):
    database = tmp_path / "replay.db"
    monkeypatch.setattr(routes, "autonomy_store", AutonomyStore(database))
    index = pd.date_range("2024-01-02", periods=140, freq="B", tz="UTC")
    close = pd.Series(range(100, 240), index=index, dtype=float)
    frame = pd.DataFrame({
        "Open": close - 0.25,
        "High": close + 1,
        "Low": close - 1,
        "Close": close,
        "Volume": 1_000_000,
    }, index=index)
    monkeypatch.setattr(
        routes.market,
        "get_price_history",
        lambda *_args, **_kwargs: frame,
    )

    created = client.post("/explosive-moves/replay", json={
        "ticker": "RPLY",
        "period": "2y",
        "forward_sessions": 20,
        "stride_sessions": 5,
        "minimum_score": 60,
    })
    history = client.get("/explosive-moves/replay/history?limit=10")
    detail = client.get(
        f"/explosive-moves/replay/history/{created.json()['history_id']}"
    )
    deleted = client.delete("/explosive-moves/replay/history")

    assert created.status_code == 200
    assert created.json()["probability_model"]["probabilities"] is None
    assert created.json()["leakage_controls"]["current_news_excluded"] is True
    assert history.json()["replays"][0]["symbol"] == "RPLY"
    assert "observations" not in history.json()["replays"][0]
    assert detail.json()["observations"]
    assert deleted.json()["deleted"] == 1

    invalid_stride = client.post("/explosive-moves/replay", json={
        "ticker": "RPLY", "period": "5y", "forward_sessions": 20,
        "stride_sessions": 1, "minimum_score": 60,
    })
    assert invalid_stride.status_code == 422


def test_execution_stress_routes_persist_summary_and_never_route_orders(
    client, monkeypatch, tmp_path
):
    database = tmp_path / "execution-stress.db"
    monkeypatch.setattr(routes, "autonomy_store", AutonomyStore(database))
    payload = {
        "symbol": "RPLY",
        "side": "buy",
        "order_type": "market",
        "quantity": 2_000,
        "reference_price": 25,
        "daily_volume": 500_000,
        "spread_bps": 12,
        "base_slippage_bps": 6,
        "max_participation_percent": 1,
        "adverse_gap_percent": 8,
        "luld_style_band_percent": 5,
        "protective_stop_price": 22,
    }

    created = client.post("/explosive-moves/execution-simulations", json=payload)
    history = client.get("/explosive-moves/execution-simulations/history?limit=10")
    detail = client.get(
        f"/explosive-moves/execution-simulations/history/{created.json()['history_id']}"
    )
    deleted = client.delete("/explosive-moves/execution-simulations/history")

    assert created.status_code == 200
    assert created.json()["probability_model"]["probabilities"] is None
    assert created.json()["regulatory_context"]["official_band_replay"] is False
    assert "no order" in created.json()["safety_boundary"].lower()
    assert history.json()["simulations"][0]["symbol"] == "RPLY"
    assert "scenarios" not in history.json()["simulations"][0]
    assert detail.json()["scenarios"][0]["id"] == "baseline"
    assert deleted.json()["deleted"] == 1

    missing_limit = client.post(
        "/explosive-moves/execution-simulations",
        json={**payload, "order_type": "limit"},
    )
    assert missing_limit.status_code == 400
    assert "Limit price is required" in missing_limit.json()["detail"]


def test_indicator_allowlist_rejects_unknown_values_before_market_call(client):
    response = client.post(
        "/orion-ai/explain-indicator",
        json={"ticker": "AAPL", "indicator": "MACD"},
    )
    assert response.status_code == 400
    assert "Unsupported indicator" in response.json()["detail"]


def test_candles_include_volume_and_reject_unknown_ranges(client, monkeypatch):
    history = pd.DataFrame(
        {"Open": [100], "High": [104], "Low": [99], "Close": [103], "Volume": [1_250_000]},
        index=pd.to_datetime(["2026-07-16"], utc=True),
    )
    monkeypatch.setattr(routes.market, "get_price_history", lambda *args, **kwargs: history)

    response = client.get("/candles/AAPL?period=1d&interval=1m")

    assert response.status_code == 200
    assert response.json()["candles"][0]["volume"] == 1_250_000
    assert response.json()["exchange_timezone"] == "America/New_York"
    assert client.get("/candles/AAPL?period=max&interval=2m").status_code == 400


def test_intraday_candles_localize_naive_exchange_time_before_utc(client, monkeypatch):
    history = pd.DataFrame(
        {"Open": [100], "High": [101], "Low": [99], "Close": [100.5], "Volume": [500]},
        index=pd.to_datetime(["2026-07-17 09:30:00"]),
    )
    monkeypatch.setattr(routes.market, "get_price_history", lambda *args, **kwargs: history)

    candle = client.get("/candles/AAPL?period=1d&interval=1m").json()["candles"][0]

    assert candle["time"] == int(pd.Timestamp("2026-07-17T13:30:00Z").timestamp())
    assert candle["market_time"].startswith("2026-07-17T09:30:00")


def test_horizon_opportunity_route_returns_discovery_metadata(client, monkeypatch):
    scan_call = {}

    class FakeStore:
        database_path = "unused"

        def get_settings(self):
            return {"candidate_count": 25, "deep_analysis_count": 3}

        def get_source(self):
            return "alpaca"

        def recent_proposal_symbols(self, _limit):
            return []

        def recent_opportunity_symbols(self, _source, _limit):
            return []

        def record_opportunity_scan_symbols(self, _source, symbols):
            return len(set(symbols))

        def save_opportunity_board(self, _horizon, _board):
            return {"history_id": 7, "saved_at": "2026-07-27 12:00:00"}

    monkeypatch.setattr(routes, "AutonomyStore", lambda _path: FakeStore())
    monkeypatch.setattr(routes._default_autonomy_store, "database_path", "unused")
    monkeypatch.setattr(routes.alpaca_broker, "status", lambda _user: {"connected": True})
    monkeypatch.setattr(routes.alpaca_broker, "positions", lambda _user: [])
    monkeypatch.setattr(routes.alpaca_broker, "account", lambda _user: {"equity": "100000", "cash": "100000"})
    def fake_scan(_broker, _user, settings, held_symbols, _recent):
        scan_call.update(settings=settings, held_symbols=held_symbols)
        return {
        "universe_size": 12000,
        "screened_symbols": 180,
        "qualified_count": 1,
        "ai_analysis_count": 1,
        "candidates": [{"symbol": "AAPL", "price": 200}],
        "_screened_symbol_list": ["AAPL"],
        }

    monkeypatch.setattr(routes.market_scanner, "scan", fake_scan)
    monkeypatch.setattr(routes, "build_alpaca_portfolio_snapshot", lambda *_args: {
        "positions": [], "total_value": 100_000, "cash": 100_000,
    })
    monkeypatch.setattr(routes, "build_orion_context", lambda symbol: {"symbol": symbol, "context_meta": {"partial_failure": False}})
    monkeypatch.setattr(
        routes,
        "load_opportunity_structure",
        lambda _horizon, _candidate: {
            "version": "market-structure-v1",
            "data_quality": True,
            "score": 90,
            "score_components": {"trend": 90},
            "trigger_status": "confirmed",
            "current_price": 200,
            "entry_price": 200,
            "entry_zone_low": 199.5,
            "entry_zone_high": 200.5,
            "breakout_price": 199.8,
            "stop_loss": 190,
            "take_profit": 230,
            "summary": "Breakout confirmed.",
            "entry_readiness": {
                "status": "technically_ready",
                "technically_ready": True,
                "current_in_entry_zone": True,
                "summary": "Technical gates passed.",
                "checks": [],
            },
        },
    )
    monkeypatch.setattr(routes.context_cache, "load", lambda *_args: ({"sector": "Technology"}, {"status": "fresh"}))
    monkeypatch.setattr(routes, "rank_horizon_opportunities", lambda horizon, evidence, portfolio: {
        "horizon": horizon,
        "market_note": "Selective.",
        "candidates": [{
            "symbol": "AAPL",
            "research_rating": "STRONG_CANDIDATE",
            "score": 85,
            "entry_price": 200,
            "stop_loss": 190,
            "take_profit": 230,
        }],
        "limitations": [],
        "prompt_version": "opportunity-board-v2",
    })
    routes.memory.set_preferences({
        "recommendation_planning_equity": 12_000,
        "recommendation_planning_cash": 7_500,
    })

    response = client.get(
        "/orion-ai/opportunities/day?setup_filter=entry_ready"
    )

    assert response.status_code == 200
    assert response.json()["horizon"] == "day"
    assert response.json()["discovery"]["screened_symbols"] == 180
    assert response.json()["discovery"]["lifetime_symbols_screened"] == 1
    assert response.json()["research_scope"]["holdings_prioritized"] is False
    assert response.json()["research_scope"]["eligible_universe"] == 12000
    assert scan_call["held_symbols"] == []
    assert scan_call["settings"]["candidate_count"] == 160
    assert scan_call["settings"]["deep_analysis_count"] == 16
    assert response.json()["paper_only"] is True
    assert response.json()["external_execution_only"] is True
    assert response.json()["risk_profile"]["mode"] == "balanced"
    assert response.json()["sizing_account"]["source"] == "manual_external_planning"
    assert response.json()["sizing_account"]["equity"] == 12_000
    assert response.json()["candidates"][0]["risk_plan"]["status"] == "qualified"
    assert response.json()["candidates"][0]["risk_plan"]["instrument"] == "REAL_SHARES"
    assert response.json()["candidates"][0]["risk_plan"]["external_execution_only"] is True
    assert response.json()["candidates"][0]["entry_ready"] is True
    assert response.json()["best_setup"]["actionable_now"] is True
    assert response.json()["entry_ready_summary"]["qualified_now"] == 1
    assert response.json()["entry_ready_summary"]["scan_mode"] == "entry_ready"
    assert response.json()["research_scope"]["setup_filter"] == "entry_ready"
    assert response.json()["history_id"] == 7

    catalyst = client.get(
        "/orion-ai/opportunities/day?setup_filter=catalyst_breakout"
    )
    assert catalyst.status_code == 200
    assert catalyst.json()["research_scope"]["setup_filter"] == "catalyst_breakout"
    assert catalyst.json()["catalyst_summary"]["evaluated"] == 1
    assert catalyst.json()["candidates"][0]["breakout_readiness"][
        "score_meaning"
    ].endswith("not probability of profit or move size")
    assert "priority_symbols" in scan_call["settings"]


def test_horizon_opportunity_route_rejects_unknown_setup_filter(client):
    response = client.get(
        "/orion-ai/opportunities/day?setup_filter=guaranteed"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Setup filter must be all, entry_ready, or catalyst_breakout"
    )


def test_horizon_opportunity_route_can_use_trading212_universe(
    client, monkeypatch
):
    scan_call = {}

    class FakeStore:
        database_path = "unused"

        def get_settings(self):
            return {"candidate_count": 25, "deep_analysis_count": 3}

        def recent_opportunity_symbols(self, source, _limit):
            assert source == "trading212_demo"
            return ["MSFT"]

        def record_opportunity_scan_symbols(self, source, symbols):
            assert source == "trading212_demo"
            assert symbols == ["AAPL_US_EQ"]
            return 37

        def save_opportunity_board(self, _horizon, _board):
            return {"history_id": 8, "saved_at": "2026-07-30 12:00:00"}

    monkeypatch.setattr(routes, "AutonomyStore", lambda _path: FakeStore())
    monkeypatch.setattr(
        routes._default_autonomy_store, "database_path", "unused"
    )
    monkeypatch.setattr(
        routes.trading212_demo,
        "status",
        lambda _user: {"connected": True},
    )
    monkeypatch.setattr(
        routes.trading212_demo,
        "instrument_universe",
        lambda _user: {
            "provider_count": 5000,
            "mapped_count": 4700,
            "unsupported_count": 300,
            "items": [],
        },
    )

    def fake_scan(universe, _market, _user, settings, **kwargs):
        scan_call.update(
            universe=universe,
            settings=settings,
            source=kwargs["source"],
            recent_symbols=kwargs["recent_symbols"],
        )
        return {
            "universe_source": "trading212_demo",
            "universe_label": "Trading 212 Demo",
            "provider_universe_size": 5000,
            "universe_size": 4700,
            "unsupported_instruments": 300,
            "screened_symbols": 100,
            "qualified_count": 1,
            "ai_analysis_count": 1,
            "candidates": [{
                "symbol": "AAPL",
                "broker_ticker": "AAPL_US_EQ",
                "instrument_name": "Apple Inc.",
                "instrument_currency": "USD",
                "price": 200,
            }],
            "_screened_symbol_list": ["AAPL_US_EQ"],
        }

    monkeypatch.setattr(
        routes.market_scanner, "scan_market_data_universe", fake_scan
    )
    monkeypatch.setattr(
        routes,
        "build_trading212_portfolio_snapshot",
        lambda _user: {
            "positions": {},
            "total_value": 5000,
            "cash": 5000,
            "currency": "EUR",
        },
    )
    monkeypatch.setattr(
        routes,
        "build_orion_context",
        lambda symbol: {
            "symbol": symbol,
            "context_meta": {"partial_failure": False},
        },
    )
    monkeypatch.setattr(
        routes.context_cache,
        "load",
        lambda *_args: ({"sector": "Technology"}, {"status": "fresh"}),
    )
    monkeypatch.setattr(
        routes,
        "rank_horizon_opportunities",
        lambda horizon, evidence, portfolio: {
            "horizon": horizon,
            "market_note": "Selective.",
            "candidates": [{
                "symbol": "AAPL",
                "research_rating": "WATCH",
                "score": 70,
                "entry_price": None,
                "stop_loss": None,
                "take_profit": None,
            }],
            "limitations": [],
            "prompt_version": "opportunity-board-v3",
        },
    )

    response = client.get(
        "/orion-ai/opportunities/swing"
        "?universe_source=trading212_demo"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["discovery"]["universe_source"] == "trading212_demo"
    assert payload["discovery"]["provider_universe_size"] == 5000
    assert payload["discovery"]["lifetime_symbols_screened"] == 37
    assert payload["candidates"][0]["broker_ticker"] == "AAPL_US_EQ"
    assert payload["sizing_account"]["source"] == "trading212_demo"
    assert payload["sizing_account"]["currency"] == "EUR"
    assert scan_call["source"] == "trading212_demo"
    assert scan_call["recent_symbols"] == ["MSFT"]


def test_recommendation_profile_is_persisted_and_rejects_unknown_modes(client):
    initial = client.get("/orion-ai/recommendation-profile")
    changed = client.put("/orion-ai/recommendation-profile", json={"mode": "aggressive"})
    planning = client.put(
        "/orion-ai/recommendation-profile",
        json={"planning_equity": 12_000, "planning_cash": 7_500},
    )
    restored = client.get("/orion-ai/recommendation-profile")
    invalid = client.put("/orion-ai/recommendation-profile", json={"mode": "maximum"})
    invalid_cash = client.put(
        "/orion-ai/recommendation-profile",
        json={"planning_equity": 5_000, "planning_cash": 6_000},
    )

    assert initial.status_code == 200
    assert initial.json()["selected_mode"] == "balanced"
    assert [item["mode"] for item in initial.json()["available_profiles"]] == [
        "conservative", "balanced", "aggressive",
    ]
    assert changed.json()["profile"]["max_instrument_leverage"] == 1
    assert planning.json()["planning_account"] == {
        "configured": True,
        "equity": 12_000.0,
        "cash": 7_500.0,
        "currency": "USD",
    }
    assert restored.json()["selected_mode"] == "aggressive"
    assert restored.json()["planning_account"]["equity"] == 12_000.0
    assert restored.json()["external_execution_only"] is True
    assert invalid.status_code == 400
    assert invalid_cash.status_code == 400


def test_opportunity_history_endpoint_returns_persisted_boards(client, monkeypatch):
    monkeypatch.setattr(routes._default_autonomy_store, "list_opportunity_boards", lambda horizon, limit: [{
        "history_id": 3,
        "horizon": horizon or "day",
        "market_note": "Saved",
        "candidates": [],
    }])

    response = client.get("/orion-ai/opportunity-history?horizon=swing&limit=10")

    assert response.status_code == 200
    assert response.json()["persistent"] is True
    assert response.json()["boards"][0]["history_id"] == 3
    assert response.json()["boards"][0]["horizon"] == "swing"


def test_opportunity_history_delete_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        routes._default_autonomy_store,
        "delete_opportunity_boards",
        lambda horizon: 4 if horizon == "swing" else 0,
    )

    response = client.delete("/orion-ai/opportunity-history?horizon=swing")

    assert response.status_code == 200
    assert response.json() == {"deleted": 4, "horizon": "swing"}


def test_paper_lab_history_clear_requires_stopped_agent(client, monkeypatch):
    monkeypatch.setattr(
        routes.agent_manager,
        "status",
        lambda user_id: {"mode": "shadow", "running": False},
    )

    response = client.delete("/autonomy/history")

    assert response.status_code == 400
    assert "Stop the Orion paper agent" in response.json()["detail"]


def test_alpaca_connection_selects_the_broker_workspace(client, monkeypatch):
    monkeypatch.setattr(routes.alpaca_broker, "connect", lambda *args: {"id": "paper", "equity": "100000"})
    monkeypatch.setattr(routes.alpaca_broker, "status", lambda *args: {"connected": True, "paper_only": True})

    response = client.post("/broker/alpaca/connect", json={"key_id": "paper-key", "secret_key": "paper-secret"})

    assert response.status_code == 200
    assert response.json()["active_source"] == "alpaca"


def test_trading212_demo_routes_are_demo_only_and_manually_confirmed(
    client, monkeypatch
):
    overview = {
        "account": {"currency": "EUR"},
        "positions": [],
        "pending_orders": [],
        "historical_orders": [],
        "transactions": [],
        "dividends": [],
        "partial_failure": False,
    }
    monkeypatch.setattr(routes.trading212_demo, "connect", lambda *args: overview)
    monkeypatch.setattr(
        routes.trading212_demo,
        "status",
        lambda *args: {
            "connected": True,
            "environment": "demo",
            "demo_only": True,
            "read_only": False,
            "order_submission_enabled": True,
            "manual_confirmation_required": True,
            "autonomous_orders_supported": False,
            "credentials_persisted": False,
            "live_trading_supported": False,
        },
    )
    monkeypatch.setattr(routes.trading212_demo, "overview", lambda *args: overview)

    connected = client.post(
        "/broker/trading212-demo/connect",
        json={"api_key": "demo-key", "api_secret": "demo-secret"},
    )
    fetched = client.get("/broker/trading212-demo/overview")
    workspace = client.get("/workspace")
    route_methods = {
        method
        for route in routes.router.routes
        if route.path.startswith("/broker/trading212-demo")
        for method in route.methods
    }
    route_paths = {
        route.path
        for route in routes.router.routes
        if route.path.startswith("/broker/trading212-demo")
    }

    assert connected.status_code == 200
    assert connected.json()["active_source"] == "trading212_demo"
    assert connected.json()["status"]["order_submission_enabled"] is True
    assert connected.json()["status"]["manual_confirmation_required"] is True
    assert fetched.json()["account"]["currency"] == "EUR"
    assert workspace.json()["active_source"] == "trading212_demo"
    assert workspace.json()["trading212_demo"]["demo_only"] is True
    assert route_methods == {"GET", "POST"}
    assert route_paths == {
        "/broker/trading212-demo/status",
        "/broker/trading212-demo/connect",
        "/broker/trading212-demo/disconnect",
        "/broker/trading212-demo/overview",
        "/broker/trading212-demo/instruments",
        "/broker/trading212-demo/orders/review",
        "/broker/trading212-demo/orders/reconcile",
        "/broker/trading212-demo/orders",
        "/broker/trading212-demo/orders/{review_id}/confirm",
        "/broker/trading212-demo/orders/{review_id}/cancel",
    }
    assert client.post("/broker/trading212-demo/orders", json={}).status_code == 405
    assert not any("autonom" in path for path in route_paths)


def test_trading212_demo_review_confirm_reconcile_and_cancel_contracts(
    client, monkeypatch
):
    review = {
        "review_id": "review-1",
        "ticker": "AAPL_US_EQ",
        "status": "reviewed",
    }
    submitted = {
        **review,
        "status": "submitted",
        "broker_order_id": "123",
    }
    monkeypatch.setattr(
        routes.trading212_demo,
        "instruments",
        lambda *_args: [{"ticker": "AAPL_US_EQ"}],
    )
    monkeypatch.setattr(
        routes.trading212_execution,
        "review",
        lambda *_args: review,
    )
    monkeypatch.setattr(
        routes.trading212_execution,
        "confirm",
        lambda *_args: submitted,
    )
    monkeypatch.setattr(
        routes.trading212_execution,
        "cancel",
        lambda *_args: {**submitted, "status": "cancellation_requested"},
    )
    monkeypatch.setattr(
        routes.trading212_execution,
        "reconcile",
        lambda *_args: {
            "orders": [submitted],
            "updated": 1,
            "journal_synced": 1,
            "overview": {},
        },
    )
    monkeypatch.setattr(
        routes.autonomy_store,
        "list_trading212_orders",
        lambda *_args: [submitted],
    )

    instruments = client.get(
        "/broker/trading212-demo/instruments?q=AAPL"
    )
    reviewed = client.post(
        "/broker/trading212-demo/orders/review",
        json={
            "ticker": "AAPL_US_EQ",
            "side": "buy",
            "order_type": "limit",
            "quantity": 1,
            "limit_price": 150,
        },
    )
    confirmed = client.post(
        "/broker/trading212-demo/orders/review-1/confirm",
        json={"confirmed": True},
    )
    reconciled = client.post("/broker/trading212-demo/orders/reconcile")
    cancelled = client.post(
        "/broker/trading212-demo/orders/review-1/cancel",
        json={"confirmed": True},
    )

    assert instruments.json()["items"][0]["ticker"] == "AAPL_US_EQ"
    assert reviewed.json()["manual_confirmation_required"] is True
    assert confirmed.json()["order"]["broker_order_id"] == "123"
    assert reconciled.json()["journal_synced"] == 1
    assert cancelled.json()["order"]["status"] == "cancellation_requested"


def test_trading212_demo_normalizes_into_orion_portfolio_contract(
    client, monkeypatch
):
    overview = {
        "account": {
            "currency": "EUR",
            "cash": {
                "availableToTrade": 4100,
                "total": 5000,
                "result": 50,
            },
            "investments": {
                "currentValue": 900,
                "unrealizedPnl": 40,
            },
        },
        "positions": [{
            "ticker": "AAPL_US_EQ",
            "quantity": 2,
            "averagePricePaid": 430,
            "currentPrice": 450,
            "ppl": 40,
        }],
        "partial_failure": True,
        "errors": {"pending_orders": "Trading 212 Demo API error (403): request rejected"},
        "permission_limited_sections": ["pending_orders"],
        "freshness": {"cache_status": "fresh"},
    }

    snapshot = routes.build_trading212_portfolio_snapshot(
        user_id="test-user",
        overview=overview,
    )

    assert snapshot["source"] == "trading212_demo"
    assert snapshot["source_label"] == "Trading 212 Demo"
    assert snapshot["read_only"] is True
    assert snapshot["currency"] == "EUR"
    assert snapshot["total_value"] == 5000
    assert snapshot["cash"] == 4100
    assert snapshot["invested_value"] == 900
    assert snapshot["unrealized_pnl"] == 40
    assert snapshot["realized_pnl"] == 10
    assert snapshot["positions"]["AAPL"]["broker_symbol"] == "AAPL_US_EQ"
    assert snapshot["positions"]["AAPL"]["market_value"] == 900
    assert snapshot["positions"]["AAPL"]["valuation_estimated"] is True
    assert snapshot["positions"]["AAPL"]["allocation_percent"] == 18


def test_trading212_demo_can_be_selected_and_disconnect_falls_back_to_local(
    client, monkeypatch
):
    overview = {
        "account": {"currency": "EUR", "cash": {"total": 5000, "availableToTrade": 5000}},
        "positions": [],
        "partial_failure": False,
        "errors": {},
        "freshness": {"cache_status": "fresh"},
    }
    monkeypatch.setattr(
        routes.trading212_demo,
        "status",
        lambda *_args: {
            "connected": True,
            "environment": "demo",
            "read_only": True,
            "credentials_persisted": False,
            "live_trading_supported": False,
        },
    )
    monkeypatch.setattr(routes.trading212_demo, "overview", lambda *_args: overview)
    monkeypatch.setattr(
        routes,
        "review_portfolio",
        lambda portfolio: {
            "question": "Which portfolio is active?",
            "answer": portfolio["source"],
        },
    )

    selected = client.put(
        "/workspace/source",
        json={"source": "trading212_demo"},
    )
    active = client.get("/portfolio/active")
    orion_review = client.post("/orion-ai/portfolio-review")
    disconnected = client.post("/broker/trading212-demo/disconnect")

    assert selected.status_code == 200
    assert selected.json()["active_source"] == "trading212_demo"
    assert active.json()["source"] == "trading212_demo"
    assert active.json()["total_value"] == 5000
    assert orion_review.json()["answer"] == "trading212_demo"
    assert disconnected.json()["active_source"] == "local"


def test_application_exposes_no_trading212_live_routes(client):
    assert not any(
        "trading212-live" in route.path
        for route in routes.router.routes
    )
    assert client.get("/broker/trading212-live/status").status_code == 404


def test_application_exposes_no_alpaca_live_routes(client):
    live_routes = [
        route.path
        for route in routes.router.routes
        if route.path.startswith("/broker/alpaca-live")
    ]

    assert live_routes == []
    assert client.get("/broker/alpaca-live/status").status_code == 404


def test_unconfigured_ai_returns_service_unavailable(client, monkeypatch):
    def unavailable(_portfolio):
        raise routes.OrionAIUnavailableError("Orion AI is not configured")

    monkeypatch.setattr(routes, "review_portfolio", unavailable)
    response = client.post("/orion-ai/portfolio-review")
    assert response.status_code == 503


def test_trade_journal_api_updates_portfolio_entry(client):
    trade = routes.paper.buy("AAPL", 100, 1)

    response = client.put(
        f"/paper/trades/{trade['id']}/journal",
        json={
            "thesis": "Trend continuation",
            "invalidation_price": 95,
            "post_trade_notes": "Good patience",
        },
    )

    assert response.status_code == 200
    portfolio = client.get("/paper/portfolio").json()
    assert portfolio["trades"][0]["journal"]["thesis"] == "Trend continuation"
    assert "expectancy" in portfolio["journal_statistics"]


def test_streaming_chat_emits_deltas_and_persists_only_complete_answer(client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "build_orion_context",
        lambda ticker: {
            "quote": {},
            "technical_analysis": {},
            "recent_news": [],
            "context_meta": {"partial_failure": False, "components": {}},
        },
    )
    monkeypatch.setattr(routes, "stream_orion_answer", lambda **kwargs: iter(["Hello", " world"]))

    response = client.post(
        "/orion-ai/chat/stream",
        json={"ticker": "AAPL", "question": "Status?", "history": []},
    )

    assert response.status_code == 200
    assert '"type": "delta", "text": "Hello"' in response.text
    assert '"type": "done"' in response.text
    history = routes.memory.get_history("AAPL")
    assert history[-1]["answer"] == "Hello world"


def test_market_context_reports_partial_provider_failure(monkeypatch):
    monkeypatch.setattr(routes, "context_cache", MarketContextCache(ttl_seconds=60))
    monkeypatch.setattr(routes.market, "get_quote", lambda ticker: (_ for _ in ()).throw(RuntimeError("quote offline")))
    monkeypatch.setattr(routes.market, "get_news", lambda ticker: {"news": [{"title": "Available"}]})
    monkeypatch.setattr(routes.market, "get_price_history", lambda ticker: (_ for _ in ()).throw(RuntimeError("history offline")))

    context = routes.build_orion_context("aapl")

    assert context["recent_news"][0]["title"] == "Available"
    assert context["context_meta"]["partial_failure"] is True
    assert context["context_meta"]["components"]["quote"]["status"] == "unavailable"


def test_portfolio_intelligence_and_simulators_have_stable_contracts(client, monkeypatch):
    routes.context_cache.clear()
    benchmark_frame = pd.DataFrame(
        {"Close": [100, 101]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
    )
    monkeypatch.setattr(routes.market, "get_price_history", lambda *args, **kwargs: benchmark_frame)

    intelligence = client.get("/portfolio/intelligence?benchmark=SPY")
    sizing = client.post(
        "/portfolio/simulate-position-size",
        json={"entry_price": 100, "stop_price": 95, "risk_percent": 1, "max_allocation_percent": 20},
    )
    rebalance = client.post(
        "/portfolio/simulate-rebalance",
        json={"targets": {"CASH": 100}},
    )

    assert intelligence.status_code == 200
    assert intelligence.json()["performance"]["status"] == "collecting_history"
    assert sizing.json()["recommended_shares"] == 20
    assert rebalance.json()["simulation_only"] is True
    assert rebalance.json()["cash"]["target_value"] == 10_000


def test_saved_strategy_backtest_alert_and_research_contracts(client, monkeypatch):
    index = pd.date_range("2026-01-01", periods=80, freq="D", tz="UTC")
    prices = list(range(140, 100, -1)) + list(range(100, 140))
    history = pd.DataFrame({
        "Open": prices, "High": [price + 1 for price in prices],
        "Low": [price - 1 for price in prices], "Close": prices,
        "Volume": [1_000] * 80,
    }, index=index)
    monkeypatch.setattr(routes.market, "get_price_history", lambda *args, **kwargs: history)
    monkeypatch.setattr(routes.market, "get_quote", lambda ticker: {"ticker": ticker, "price": 120})
    monkeypatch.setattr(routes.market, "get_earnings_calendar", lambda ticker: {"ticker": ticker, "earnings": []})
    monkeypatch.setattr(routes.market, "get_analyst_ratings", lambda ticker: {"ticker": ticker, "summary": []})
    monkeypatch.setattr(routes.market, "get_insider_activity", lambda ticker: {"ticker": ticker, "transactions": []})
    monkeypatch.setattr(routes.market, "get_news", lambda ticker: [])
    routes.context_cache.clear()

    saved = client.post("/strategies", json={"name": "Cross", "ticker": "AAPL", "kind": "sma_crossover", "parameters": {"fast_period": 5, "slow_period": 15}, "period": "1y"})
    strategy_id = saved.json()["strategy"]["id"]
    backtest = client.post(f"/strategies/{strategy_id}/backtest")
    alert = client.post("/alerts", json={"ticker": "AAPL", "alert_type": "price_above", "threshold": 110})
    checked = client.post("/alerts/check")
    research = client.get("/research/AAPL")

    assert saved.status_code == 200
    assert backtest.status_code == 200
    assert "metrics" in backtest.json()
    assert alert.status_code == 200
    assert checked.json()["triggered_count"] == 1
    assert research.json()["data_quality"]["partial_failure"] is False
    assert research.json()["strategy_analysis"]["data_quality"]["sufficient"] is False
    assert len(research.json()["strategy_analysis"]["strategies"]) == 9


def test_strategy_research_rejects_a_pair_with_the_same_ticker(client):
    response = client.get("/research/AAPL?peer=aapl")

    assert response.status_code == 400
    assert response.json()["detail"] == "Pair ticker must differ from the selected ticker"


def test_predictive_training_route_persists_dataset_and_model_contract(
    client, monkeypatch, tmp_path
):
    database = tmp_path / "predictive-train.db"
    monkeypatch.setattr(routes, "autonomy_store", AutonomyStore(database))
    liquidity_row = {
        "symbol": "AAPL", "liquidity_tier": "A", "liquidity_score": 92,
        "metrics": {"spread_bps": 4},
    }
    monkeypatch.setattr(routes, "_execute_liquidity_ranking", lambda *_args, **_kwargs: {
        "rankings": [liquidity_row], "history_id": 1,
    })
    frame = pd.DataFrame({"Close": [100, 101]})
    monkeypatch.setattr(routes.market, "get_intraday_histories", lambda *_args, **_kwargs: {
        "histories": {"AAPL": frame, "SPY": frame}, "errors": [],
    })
    monkeypatch.setattr(routes, "build_intraday_feature_frame", lambda *_args, **_kwargs: frame)
    monkeypatch.setattr(routes, "build_training_samples", lambda *_args, **_kwargs: [
        {"horizon": "1m", "timestamp": "2026-01-01T00:00:00Z"}
    ] * 150)
    monkeypatch.setattr(routes, "train_predictive_model", lambda samples, name: {
        "version": "orion-predictive-model-v1", "name": name,
        "split_contract": "chronological", "safety_boundary": "Research only",
        "reliable_horizons": [],
        "horizons": {"1m": {
            "status": "experimental_baseline", "sample_count": len(samples),
            "probabilities_available": True, "reliable": False,
            "holdout": {"accuracy": 0.4},
        }},
    })

    response = client.post("/predictive-intelligence/models/train", json={
        "name": "Test", "candidate_count": 10, "training_symbol_count": 2,
    })

    assert response.status_code == 200
    assert response.json()["dataset"]["sample_count"] == 150
    assert response.json()["dataset"]["thirty_second_status"] == "unavailable_from_one_minute_history"
    assert PredictiveIntelligenceStore(database).latest_model()["name"] == "Test"


def test_live_edge_route_persists_auditable_no_trade_result(
    client, monkeypatch, tmp_path
):
    database = tmp_path / "predictive-live.db"
    monkeypatch.setattr(routes, "autonomy_store", AutonomyStore(database))
    store = PredictiveIntelligenceStore(database)
    saved = store.save_model({
        "name": "Baseline", "reliable_horizons": [],
        "horizons": {"1m": {
            "status": "experimental_baseline", "sample_count": 500,
            "probabilities_available": True, "reliable": False, "holdout": {},
        }},
    }, {"sample_count": 500})
    row = {
        "symbol": "AAPL", "liquidity_tier": "A", "liquidity_score": 90,
        "liquidity_percentile": 100, "metrics": {"spread_percent": 0.02},
    }
    monkeypatch.setattr(routes, "_execute_liquidity_ranking", lambda *_args, **_kwargs: {
        "rankings": [row], "history_id": 2,
    })
    history = pd.DataFrame({"Close": [100, 101]})
    monkeypatch.setattr(routes.market, "get_intraday_histories", lambda *_args, **_kwargs: {
        "histories": {"AAPL": history, "SPY": history}, "errors": [],
    })
    monkeypatch.setattr(routes, "build_intraday_feature_frame", lambda *_args, **_kwargs: history)
    monkeypatch.setattr(routes, "latest_historical_snapshot", lambda *_args: {
        "timestamp": "2026-08-26T10:00:00+00:00", "price": 100,
        "features": {"return_1m": 0.001}, "feature_coverage_percent": 70,
    })
    monkeypatch.setattr(routes, "classify_market_regime", lambda *_args: {
        "regime": "range_chop", "label": "Range Chop", "status": "classified",
    })
    monkeypatch.setattr(routes.stream_manager, "event_page", lambda *_args, **_kwargs: {"events": []})
    monkeypatch.setattr(routes.real_time_feature_engine, "snapshot", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("empty")))
    monkeypatch.setattr(routes, "build_live_prediction", lambda *_args, **_kwargs: {
        "timestamp": "2026-08-26T10:00:00+00:00",
        "due_at": "2026-08-26T10:01:00+00:00", "ticker": "AAPL",
        "price": 100, "horizon": "1m", "P_UP": 0.4, "P_DOWN": 0.3,
        "P_NEUTRAL": 0.3, "direction": "NO_TRADE", "model_direction": "UP",
        "verdict": "NO TRADE — NO STATISTICAL EDGE",
        "feature_snapshot": {"features": {}}, "expected_value": {},
        "liquidity_score": 90, "liquidity_tier": "A",
        "opportunity_score": {"score": 40}, "market_regime": {"regime": "range_chop"},
        "confidence": "experimental_unvalidated",
    })

    response = client.post("/predictive-intelligence/live-edge/scan", json={
        "candidate_count": 3, "horizons": ["1m"], "symbols": ["AAPL"],
    })

    assert response.status_code == 200
    assert response.json()["empty_edge_message"] == "NO TRADE — NO STATISTICAL EDGE"
    assert response.json()["selection_mode"] == "selected_tickers"
    assert response.json()["selected_tickers"] == ["AAPL"]
    assert response.json()["liquid_research_watch"][0]["prediction_id"] > 0
    assert store.list_predictions()[0]["model_id"] == saved["model_id"]
    route_source = inspect.getsource(routes.scan_live_edge)
    assert "submit_order" not in route_source
    assert "trading212_execution" not in route_source
