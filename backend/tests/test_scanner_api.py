"""Only the scanner endpoint and its lifecycle/connection hooks are exercised."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import routes
from test_continuous_scanner import build


@pytest.fixture
def scanner_client(tmp_path, monkeypatch):
    scheduler, runner, clock, _, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    monkeypatch.setenv("ORION_AUTH_DISABLED", "false")
    sessions = {name: {"user": {"id": name}, "csrf_token": "csrf"} for name in ("alice", "bob")}
    auth = SimpleNamespace(authenticate=lambda token: sessions.get(token), logout=Mock(),
                           user_database=lambda user: tmp_path / user / "orion.db")
    monkeypatch.setattr(main, "auth_store", auth)
    monkeypatch.setattr(main, "activate_user_scope", lambda *args: None)
    monkeypatch.setattr(main, "deactivate_user_scope", lambda token: None)
    monkeypatch.setattr(main, "scanner_scheduler", scheduler)
    monkeypatch.setattr(main.app.state, "scanner_scheduler", scheduler)
    return TestClient(main.app), scheduler, runner, clock


def test_current_state_endpoint_requires_authentication(scanner_client):
    client, _, runner, _ = scanner_client
    assert client.get("/scanner/current").status_code == 401
    assert len(runner.calls) == 1


def test_endpoint_returns_user_scoped_structured_state_without_running_scan(scanner_client):
    client, _, runner, clock = scanner_client
    client.cookies.set("orion_session", "alice")
    response = client.get("/scanner/current")
    assert response.status_code == 200
    state = response.json()
    assert {"status", "generated_at", "freshness", "scanner_running", "universe", "active_candidates", "top_candidates", "diagnostics"} <= set(state)
    assert state["freshness"]["state"] == "delayed"
    assert state["top_candidates"][0]["probability_up"] == .73
    assert state["top_candidates"][0]["final_decision"] == "NO_TRADE"
    client.cookies.set("orion_session", "bob")
    assert client.get("/scanner/current?user_id=alice").json()["top_candidates"] == []
    client.cookies.set("orion_session", "alice")
    clock.advance(121)
    assert client.get("/scanner/current").json()["freshness"]["state"] == "stale"
    assert len(runner.calls) == 1
    assert client.post("/scanner/current", headers={"X-CSRF-Token": "csrf"}).status_code == 405


def test_fastapi_lifecycle_starts_and_stops_scanner(scanner_client, monkeypatch):
    _, scheduler, _, _ = scanner_client
    monkeypatch.setattr(main, "settlement_scheduler", SimpleNamespace(start=Mock(), stop=Mock()))
    monkeypatch.setattr(main.core_job_manager, "stop_all", Mock())
    monkeypatch.setattr(main.stream_manager, "stop_all", Mock())
    with TestClient(main.app):
        assert scheduler.thread and scheduler.thread.is_alive()
    assert not scheduler.thread.is_alive()


def test_logout_deactivates_scanner_without_provider_calls(scanner_client, monkeypatch):
    client, scheduler, runner, clock = scanner_client
    client.cookies.set("orion_session", "alice")
    monkeypatch.setattr(main.core_job_manager, "stop_user", Mock())
    monkeypatch.setattr(main.stream_manager, "stop", Mock())
    assert client.post("/auth/logout", headers={"X-CSRF-Token": "csrf"}).status_code == 200
    assert scheduler.current_state("alice")["session_active"] is False
    clock.advance(600)
    assert scheduler.run_due_once(now=clock())["status"] == "idle"
    assert len(runner.calls) == 1


def test_login_resumes_only_the_authenticated_users_connected_scanner(scanner_client, monkeypatch):
    client, scheduler, _, _ = scanner_client
    session = {"user": {"id": "alice"}, "token": "synthetic-session", "csrf_token": "csrf", "expires_at": "2026-09-01T00:00:00Z"}
    monkeypatch.setattr(main.auth_store, "login", lambda *args: session, raising=False)
    monkeypatch.setattr(routes.alpaca_broker, "status", lambda _: {"connected": True})
    activate = Mock()
    monkeypatch.setattr(scheduler, "activate_user", activate)
    response = client.post("/auth/login", json={"email": "synthetic@example.com", "password": "synthetic-password"})
    assert response.status_code == 200
    activate.assert_called_once_with("alice", main.auth_store.user_database("alice"))


def test_alpaca_connection_registers_scanner_and_disconnect_cancels_it(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_AUTH_DISABLED", "true")
    scheduler = SimpleNamespace(activate_user=Mock(), deactivate_user=Mock())
    monkeypatch.setattr(main.app.state, "scanner_scheduler", scheduler)
    monkeypatch.setattr(routes, "autonomy_store", SimpleNamespace(
        database_path=tmp_path / "user.db", set_source=lambda *_: "alpaca", get_source=lambda: "alpaca", add_event=Mock()))
    monkeypatch.setattr(routes.alpaca_broker, "connect", lambda *_: {"id": "paper"})
    monkeypatch.setattr(routes.alpaca_broker, "status", lambda *_: {"connected": True})
    monkeypatch.setattr(routes.alpaca_broker, "disconnect", Mock())
    monkeypatch.setattr(routes.alpaca_broker, "cancel_autonomous_orders", Mock())
    monkeypatch.setattr(routes.agent_manager, "kill", Mock())
    monkeypatch.setattr(main.core_job_manager, "stop_user", Mock())
    monkeypatch.setattr(routes.stream_manager, "stop", Mock())
    client = TestClient(main.app)
    assert client.post("/broker/alpaca/connect", json={"key_id": "synthetic", "secret_key": "synthetic"}).status_code == 200
    scheduler.activate_user.assert_called_once_with("test-user", tmp_path / "user.db", restart=True)
    assert client.post("/broker/alpaca/disconnect").status_code == 200
    scheduler.deactivate_user.assert_called_once_with("test-user")
