"""Runtime activation regression: authenticated HTTP -> real runner -> read API.

Only transport responses and time are synthetic; no network, training or sleep.
"""
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import main
from app.services.continuous_scanner import ScannerScheduler
from app.services.scanner_runtime import (
    ExistingScannerRunner, MarketClosed, MarketSessionUnverified, scanner_provider_availability,
)
from app.services.scanner_state_store import ScannerStateStore
from test_continuous_scanner import build, Clock, settings
from test_scanner_api import scanner_client
from test_scanner_runtime import SmallBatchMarket
from test_staged_scanner_adapters import Broker, NOW
from test_market_intelligence import row, merge


def test_restored_browser_session_queues_first_page_without_restarting_on_each_read(scanner_client):
    client, scheduler, runner, clock = scanner_client
    scheduler.deactivate_user("alice")
    clock.advance(60)
    client.cookies.set("orion_session", "alice")
    assert client.get("/auth/session").status_code == 200
    original = scheduler.sessions["alice"]
    assert not original.cancel.is_set() and scheduler.wake.is_set()
    assert scheduler.run_due_once(now=clock())["status"] == "completed"
    assert runner.calls[-1] == ["CCC", "DDD"]
    next_broad = original.state["next_broad_at"]
    for _ in range(3):
        assert client.get("/auth/session").status_code == 200
    assert scheduler.sessions["alice"] is original
    assert not original.cancel.is_set()
    assert original.state["next_broad_at"] == next_broad
    assert len(runner.calls) == 2


def test_unauthenticated_restore_does_not_activate(scanner_client, monkeypatch):
    client, scheduler, _, _ = scanner_client
    activate = Mock()
    monkeypatch.setattr(scheduler, "activate_user", activate)
    assert client.get("/auth/session").status_code == 401
    activate.assert_not_called()


def test_registration_runs_the_same_activation_check(scanner_client, monkeypatch):
    client, scheduler, _, _ = scanner_client
    session = {"user": {"id": "bob"}, "token": "fixture", "csrf_token": "csrf", "expires_at": "fixture"}
    monkeypatch.setattr(main.auth_store, "register", lambda *args: session, raising=False)
    activate = Mock()
    monkeypatch.setattr(scheduler, "activate_user", activate)
    assert client.post("/auth/register", json={"email": "fixture@example.com", "password": "fixture-password"}).status_code == 200
    activate.assert_called_once_with("bob", main.auth_store.user_database("bob"))


def test_real_runtime_path_restores_then_scans_and_uses_yahoo_without_a_model(scanner_client, tmp_path, monkeypatch):
    client, _, _, _ = scanner_client
    market, broker, clock = SmallBatchMarket(), Broker(("MOVE",)), Clock()
    broker.status = lambda user: {"connected": user == "alice"}
    runners = []
    def factory(user, database, cancel):
        runner = ExistingScannerRunner(market, broker, user, lambda: None, settings(), cancel)
        runner.cache.wait = lambda seconds: False
        runner.cache.wall_clock = clock
        runners.append(runner)
        return runner
    scheduler = ScannerScheduler(ScannerStateStore(tmp_path / "real-runtime.db"), factory,
        lambda user: scanner_provider_availability(market, broker, user), settings(), clock=clock)
    monkeypatch.setattr(main, "scanner_scheduler", scheduler)
    monkeypatch.setattr(main.app.state, "scanner_scheduler", scheduler)
    client.cookies.set("orion_session", "alice")
    assert client.get("/auth/session").status_code == 200
    starting = client.get("/scanner/current").json()
    assert starting["status"] == "starting"
    assert starting["provider_availability"]["available"] is True
    assert not broker.snapshot_calls  # GET remains read-only
    assert scheduler.run_due_once(now=clock())["status"] == "completed"
    current = client.get("/scanner/current").json()
    assert current["universe"]["total_symbols"] == 1
    assert current["universe"]["current_page"] == 1
    assert current["status"] == "no_high_quality_candidates"  # no fitted model, never fabricated
    assert broker.snapshot_calls == [["MOVE"]]
    assert market.daily_calls == [["MOVE"]]
    assert market.minute_calls == [["MOVE", "SPY"]]
    intelligence = client.get("/scanner/market-intelligence").json()
    assert intelligence["categories"]["most_active"]["items"][0]["ticker"] == "MOVE"
    assert intelligence["categories"]["momentum_leaders"]["items"][0]["freshness"]["state"] == "delayed"
    client.get("/scanner/current")
    assert len(broker.snapshot_calls) == len(runners) == 1
    client.cookies.set("orion_session", "bob")
    client.get("/auth/session")
    missing = client.get("/scanner/current").json()
    assert missing["provider_availability"]["reason_code"] == "alpaca_credentials_missing"
    assert "bob" not in scheduler.sessions


def test_provider_configuration_is_independent_of_market_open_and_does_not_make_requests():
    broker = SimpleNamespace(status=lambda user: {"connected": True}, clock=Mock(side_effect=AssertionError("No clock in readiness")))
    availability = scanner_provider_availability(SmallBatchMarket(), broker, "alice")
    assert availability["available"] is True
    assert availability["capabilities"]["history_feed_delayed"] is True
    broker.clock.assert_not_called()


def test_missing_credentials_do_not_turn_yahoo_history_into_a_fake_snapshot_source():
    broker = SimpleNamespace(status=lambda user: {"connected": False})
    info = scanner_provider_availability(SmallBatchMarket(), broker, "alice")
    assert info["reason_code"] == "alpaca_credentials_missing"
    assert info["capabilities"]["history_client_available"] is True
    assert info["capabilities"]["yahoo_standalone_scanner"] is False
    assert "backend restart" in info["message"]
    assert "Data & account" in info["message"]


def test_missing_history_client_and_configuration_errors_are_explicit_and_redacted():
    broker = SimpleNamespace(status=lambda user: {"connected": True})
    info = scanner_provider_availability(object(), broker, "alice")
    assert info["reason_code"] == "yahoo_history_client_unavailable" and not info["available"]
    broker.status = Mock(side_effect=ValueError("private-token"))
    info = scanner_provider_availability(SmallBatchMarket(), broker, "alice")
    assert info["reason_code"] == "provider_configuration_check_failed"
    assert "private-token" not in str(info)


@pytest.mark.parametrize("session_state,error", [(False, MarketClosed), (None, MarketSessionUnverified)])
def test_runner_distinguishes_closed_from_unverified_clock(session_state, error):
    market, broker = SmallBatchMarket(), Broker()
    broker.clock = lambda user: {"is_open": session_state}
    runner = ExistingScannerRunner(market, broker, "alice", lambda: None, settings(), Event())
    with pytest.raises(error):
        runner.prepare()
    assert not market.daily_calls and not market.minute_calls and not broker.snapshot_calls


def test_closed_first_scan_reports_connected_then_open_scan_recovers(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    runner.prepare = Mock(side_effect=MarketClosed())
    scheduler.run_due_once(now=clock())
    state = scheduler.current_state("alice")
    assert state["status"] == "market_closed"
    assert state["provider_availability"]["available"] is True
    assert state["session_active"] is True
    assert "provider is connected" in state["message"]
    assert not runner.calls
    clock.advance(scheduler.settings.broad_interval_seconds)
    runner.prepare = Mock()
    assert scheduler.run_due_once(now=clock())["status"] == "completed"
    assert scheduler.current_state("alice")["universe"]["current_page"] == 1


def test_closed_market_preserves_previous_results_and_prior_session_category_history(tmp_path):
    scheduler, runner, clock, store, _ = build(tmp_path)
    scheduler.run_due_once(now=clock())
    session = scheduler.sessions["alice"]
    original = deepcopy(session.state["snapshot"])
    session.state["market_intelligence"] = merge(rows=[row("MOVE")])
    clock.advance(4 * 86400)  # Saturday; no next-session observations invented
    runner.prepare = Mock(side_effect=MarketClosed())
    scheduler.run_due_once(now=clock())
    state = scheduler.current_state("alice")
    assert state["status"] == "stale"
    assert state["last_known_candidates"] and not state["top_candidates"]
    assert store.load("alice")["snapshot"] == original
    data = scheduler.market_intelligence("alice")
    assert not data["categories"]["most_active"]["items"]
    assert data["categories"]["most_active"]["last_known"][0]["ticker"] == "MOVE"
    assert data["coverage"]["observation_session_date"] == "2026-08-25"
    assert data["coverage"]["session_date"] != "2026-08-25"


def test_unverified_session_does_not_claim_missing_credentials(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    runner.prepare = Mock(side_effect=MarketSessionUnverified())
    scheduler.run_due_once(now=clock())
    state = scheduler.current_state("alice")
    assert state["provider_availability"]["available"] is True
    assert state["diagnostics"]["last_failure"]["reason"] == "market_session_unverified"


@pytest.mark.parametrize("code,meaning", [(401, "credentials were rejected"), (403, "permissions/entitlements"), (429, "rate limit")])
def test_provider_http_failures_report_safe_exact_status(tmp_path, code, meaning):
    scheduler, runner, clock, _, _ = build(tmp_path)
    runner.prepare = Mock(side_effect=ValueError(f"Alpaca paper API error ({code}): private-token"))
    scheduler.run_due_once(now=clock())
    state = scheduler.current_state("alice")
    assert state["diagnostics"]["last_failure"]["reason"] == f"alpaca_http_{code}"
    assert meaning in state["message"]
    assert "private-token" not in str(state)


def test_disabled_scanner_does_not_create_runner_or_report_missing_provider(tmp_path):
    factory = Mock()
    scheduler = ScannerScheduler(ScannerStateStore(tmp_path / "disabled.db"), factory, lambda user: True, settings(enabled=False))
    assert scheduler.activate_user("alice", tmp_path / "alice.db") is False
    factory.assert_not_called()
    state = scheduler.current_state("alice")
    assert state["status"] == "disabled"
    assert "ORION_SCANNER_ENABLED=false" in state["message"]


def test_explicit_reconnection_replaces_runner_but_session_restoration_does_not(tmp_path):
    scheduler, _, _, _, _ = build(tmp_path)
    old = scheduler.sessions["alice"]
    assert scheduler.activate_user("alice", tmp_path / "alice.db") is False
    assert scheduler.activate_user("alice", tmp_path / "alice.db", restart=True) is True
    assert old.cancel.is_set()
    assert scheduler.sessions["alice"] is not old
