import sqlite3

from starlette.testclient import TestClient

from app import main
from app.api import routes
from app.services.alpaca_broker import AlpacaPaperBroker
from app.services.auth_store import AuthStore


def test_auth_sessions_hash_passwords_and_first_user_claims_legacy_data(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with sqlite3.connect(data / "orion.db") as connection:
        connection.execute("CREATE TABLE legacy_marker (value TEXT)")
        connection.execute("INSERT INTO legacy_marker VALUES ('mine')")
    store = AuthStore(data_root=data)
    session = store.register("owner@example.com", "a-secure-password")

    assert store.authenticate(session["token"])["user"]["email"] == "owner@example.com"
    with sqlite3.connect(store.database_path) as connection:
        encoded = connection.execute("SELECT password_hash FROM users").fetchone()[0]
    assert "a-secure-password" not in encoded
    with sqlite3.connect(store.user_database(session["user"]["id"])) as connection:
        assert connection.execute("SELECT value FROM legacy_marker").fetchone()[0] == "mine"
    store.logout(session["token"])
    assert store.authenticate(session["token"]) is None


def test_user_service_scope_isolates_orion_memory(tmp_path):
    first = routes.activate_user_scope("first", tmp_path / "first.db")
    routes.memory.add_exchange("AAPL", "First?", "First answer")
    routes.deactivate_user_scope(first)
    second = routes.activate_user_scope("second", tmp_path / "second.db")
    assert routes.memory.get_history("AAPL") == []
    routes.memory.add_exchange("AAPL", "Second?", "Second answer")
    routes.deactivate_user_scope(second)
    first = routes.activate_user_scope("first", tmp_path / "first.db")
    assert routes.memory.get_history("AAPL")[0]["question"] == "First?"
    routes.deactivate_user_scope(first)


def test_user_service_scope_isolates_opportunity_history(tmp_path):
    first = routes.activate_user_scope("first-history", tmp_path / "first-history.db")
    routes.autonomy_store.save_opportunity_board("day", {
        "horizon": "day", "market_note": "First user's board", "candidates": [],
    })
    routes.deactivate_user_scope(first)

    second = routes.activate_user_scope("second-history", tmp_path / "second-history.db")
    assert routes.autonomy_store.list_opportunity_boards() == []
    routes.deactivate_user_scope(second)

    first = routes.activate_user_scope("first-history", tmp_path / "first-history.db")
    assert routes.autonomy_store.list_opportunity_boards()[0]["market_note"] == "First user's board"
    routes.deactivate_user_scope(first)


def test_user_service_scope_isolates_predictive_models(tmp_path):
    first = routes.activate_user_scope("first-predictive", tmp_path / "first-predictive.db")
    first_store = routes._predictive_store()
    first_store.save_model({
        "name": "First model", "reliable_horizons": [],
        "horizons": {"1m": {"status": "experimental", "sample_count": 120, "reliable": False}},
    }, {"sample_count": 120})
    routes.deactivate_user_scope(first)

    second = routes.activate_user_scope("second-predictive", tmp_path / "second-predictive.db")
    assert routes._predictive_store().latest_model() is None
    routes.deactivate_user_scope(second)

    first = routes.activate_user_scope("first-predictive", tmp_path / "first-predictive.db")
    assert routes._predictive_store().latest_model()["name"] == "First model"
    routes.deactivate_user_scope(first)

def test_user_service_scope_isolates_recommendation_profile_and_planning_capital(tmp_path):
    first = routes.activate_user_scope("first-risk", tmp_path / "first-risk.db")
    routes.memory.set_preferences({
        "risk_tolerance": "aggressive",
        "recommendation_planning_equity": 12_000,
        "recommendation_planning_cash": 7_500,
    })
    routes.deactivate_user_scope(first)

    second = routes.activate_user_scope("second-risk", tmp_path / "second-risk.db")
    assert routes.recommendation_profile_response()["selected_mode"] == "balanced"
    assert routes.recommendation_profile_response()["planning_account"]["configured"] is False
    routes.deactivate_user_scope(second)

    first = routes.activate_user_scope("first-risk", tmp_path / "first-risk.db")
    restored = routes.recommendation_profile_response()
    assert restored["selected_mode"] == "aggressive"
    assert restored["planning_account"]["equity"] == 12_000
    routes.deactivate_user_scope(first)


def test_auth_middleware_requires_cookie_and_csrf(tmp_path, monkeypatch):
    store = AuthStore(data_root=tmp_path / "data")
    monkeypatch.setattr(main, "auth_store", store)
    monkeypatch.setenv("ORION_AUTH_DISABLED", "false")
    client = TestClient(main.app)
    unauthorized = client.get("/watchlist", headers={"Origin": "http://localhost:5173"})
    assert unauthorized.status_code == 401
    assert unauthorized.headers["access-control-allow-origin"] == "http://localhost:5173"
    registered = client.post("/auth/register", json={"email": "user@example.com", "password": "another-secure-password"})
    assert registered.status_code == 200
    assert client.get("/watchlist").status_code == 200
    assert client.post("/watchlist/AAPL").status_code == 403
    csrf = registered.json()["csrf_token"]
    assert client.post("/watchlist/AAPL", headers={"X-CSRF-Token": csrf}).status_code == 200


def test_logout_stops_the_users_stream_before_destroying_session(tmp_path, monkeypatch):
    store = AuthStore(data_root=tmp_path / "data")
    stopped = []

    class FakeStreamManager:
        def stop(self, user_id):
            stopped.append(user_id)

        def stop_all(self):
            return None

    monkeypatch.setattr(main, "auth_store", store)
    monkeypatch.setattr(main, "stream_manager", FakeStreamManager())
    monkeypatch.setenv("ORION_AUTH_DISABLED", "false")
    client = TestClient(main.app)
    registered = client.post(
        "/auth/register",
        json={"email": "stream-owner@example.com", "password": "another-secure-password"},
    )

    response = client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": registered.json()["csrf_token"]},
    )

    assert response.status_code == 200
    assert stopped == [registered.json()["user"]["id"]]


def test_alpaca_is_paper_only_ephemeral_and_double_gated(monkeypatch):
    broker = AlpacaPaperBroker()
    calls = []
    def fake_request(user_id, method, path, payload=None):
        calls.append((method, path, payload))
        return {"id": "paper-account", "status": "ACTIVE"} if path == "/v2/account" else {"id": "order-1"}
    monkeypatch.setattr(broker, "_request", fake_request)
    broker.connect("user", "key", "secret")
    assert broker.status("user")["credentials_persisted"] is False
    monkeypatch.setenv("ALPACA_ORDER_SUBMISSION_ENABLED", "false")
    try:
        broker.submit_order("user", "AAPL", 1, "buy", "market", "day", None, True)
        assert False, "disabled orders must fail"
    except ValueError as exc:
        assert "disabled" in str(exc)
    monkeypatch.setenv("ALPACA_ORDER_SUBMISSION_ENABLED", "true")
    try:
        broker.submit_order("user", "AAPL", 1, "buy", "market", "day", None, False)
        assert False, "an explicit review confirmation must be required"
    except ValueError as exc:
        assert "confirmation" in str(exc).lower()
    order = broker.submit_order("user", "AAPL", 1, "buy", "market", "day", None, True)
    assert order["id"] == "order-1"
    assert calls[-1][1] == "/v2/orders"
    broker.disconnect("user")
    assert broker.status("user")["connected"] is False


def test_autonomous_alpaca_orders_have_an_independent_server_gate(monkeypatch):
    broker = AlpacaPaperBroker()
    broker._credentials["user"] = ("key", "secret")
    submitted = []
    monkeypatch.setattr(broker, "_request", lambda user_id, method, path, payload=None, **kwargs: submitted.append(payload) or {"id": "auto-order"})
    monkeypatch.setenv("ALPACA_ORDER_SUBMISSION_ENABLED", "true")
    monkeypatch.setenv("ORION_AUTONOMY_ENABLED", "false")
    try:
        broker.submit_autonomous_order("user", "AAPL", 1, "buy", 100)
        assert False, "autonomous server gate must fail closed"
    except ValueError as exc:
        assert "autonomous" in str(exc).lower()
    monkeypatch.setenv("ORION_AUTONOMY_ENABLED", "true")
    assert broker.submit_autonomous_order("user", "AAPL", 1, "buy", 100)["id"] == "auto-order"
    assert submitted[-1]["type"] == "limit"
    assert submitted[-1]["time_in_force"] == "day"
    assert submitted[-1]["client_order_id"].startswith("orion-auto-")


def test_market_candidate_screener_prioritizes_activity_before_movers(monkeypatch):
    broker = AlpacaPaperBroker()
    broker._credentials["user"] = ("key", "secret")

    def fake_request(_user_id, _method, path, **_kwargs):
        if "most-actives" in path:
            return {"most_actives": [{"symbol": "ACTIVE1"}, {"symbol": "ACTIVE2"}]}
        return {
            "gainers": [{"symbol": "GAIN1"}, {"symbol": "GAIN2"}],
            "losers": [{"symbol": "LOSS1"}, {"symbol": "LOSS2"}],
        }

    monkeypatch.setattr(broker, "_request", fake_request)
    symbols, errors = broker.market_candidates("user", 10)

    assert errors == []
    assert symbols[:6] == [
        "ACTIVE1", "ACTIVE2", "GAIN1", "GAIN2", "LOSS1", "LOSS2",
    ]
