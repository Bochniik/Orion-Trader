"""Closed-startup runtime integration with deterministic provider responses."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pandas as pd
import pytest

from app.services.scanner_completed_session import completed_sessions, historical_row
from app.services.scanner_runtime import ExistingScannerRunner
from app.services.scanner_settings import ScannerSettings
from app.services.continuous_scanner import ScannerScheduler
from app.services.scanner_state_store import ScannerStateStore
from test_scanner_api import scanner_client

NOW = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)
CALENDAR = [{"date": day, "open": "09:30", "close": "16:00"}
            for day in ("2026-09-01", "2026-09-02", "2026-09-03")]


def history():
    frame = pd.DataFrame({"Close": 100., "Volume": 5_000_000.},
                         index=pd.date_range("2026-08-03", "2026-09-03", freq="B", tz="UTC"))
    frame.loc["2026-09-02", "Close"] = 104
    frame.loc["2026-09-02", "Volume"] = 10_000_000
    frame.loc["2026-09-03", "Close"] = 999  # Unfinished today: must never leak.
    return frame


def fixture(tmp_path, frame=None):
    clock = [NOW]
    settings = replace(ScannerSettings(), page_size=2, activity_limit=2, fast_limit=2, full_analysis_limit=2, result_limit=2, active_limit=2)
    broker = Mock()
    broker.clock.return_value = {"is_open": False, "next_open": "2026-09-03T13:30:00Z"}
    broker.calendar.return_value = CALENDAR
    broker.assets.return_value = [{"symbol": s, "tradable": True, "status": "active", "class": "us_equity"}
                                  for s in ("AAA", "BBB", "CCC")]
    market, loader = Mock(), Mock(side_effect=AssertionError("No closed-session model calls"))
    dataset = history() if frame is None else frame
    market.get_liquidity_histories.side_effect = lambda symbols, **kw: {
        "histories": {s: dataset.copy() for s in symbols}, "errors": []}
    runners = []
    def factory(user, path, cancel):
        runner = ExistingScannerRunner(market, broker, user, loader, settings, cancel)
        runner.cache.clock = lambda: clock[0].timestamp()
        runner.cache.wall_clock = lambda: clock[0]
        runner.cache.wait = lambda seconds: False
        runners.append(runner)
        return runner
    store = ScannerStateStore(tmp_path / "scanner.sqlite")
    scheduler = ScannerScheduler(store, factory, lambda user: True, settings, clock=lambda: clock[0])
    scheduler.activate_user("alice", tmp_path / "user.sqlite")
    return scheduler, store, clock, market, broker, loader, runners


def test_closed_startup_publishes_real_provider_rows_without_models_or_live_snapshots(tmp_path):
    scheduler, store, clock, market, broker, loader, _ = fixture(tmp_path)
    assert scheduler.run_due_once()["status"] == "historical_completed"
    response = scheduler.market_intelligence("alice")
    assert response["display_mode"] == "historical"
    assert response["session_date"] == "2026-09-02"
    assert not response["partial_failure"]
    rows = response["categories"]["most_active"]
    assert rows["items"] == []
    assert len(rows["last_known"]) == 2
    row = rows["last_known"][0]
    assert row["current_price"] == 104
    assert row["change_percent"] == pytest.approx(4)
    assert row["relative_volume"] == 2
    assert row["raw_timestamp"] == "2026-09-02T00:00:00+00:00"
    assert row["data_timestamp"] == "2026-09-02T16:00:00-04:00"
    assert row["freshness"]["state"] == "stale"
    assert row["historical"] and row["trade_recommendation"] is False
    for key in ("buy_pressure", "sell_pressure", "potential_bargains", "momentum_leaders"):
        assert response["categories"][key]["last_known"] == []
    current = scheduler.current_state("alice")
    assert current["status"] == "market_closed"
    assert current["universe"]["next_offset"] == 2
    assert current["top_candidates"] == []
    assert store.load("alice")["market_intelligence"] == {}
    broker.snapshots.assert_not_called()
    loader.assert_not_called()
    market.get_intraday_histories.assert_not_called()


def test_cross_page_aggregation_and_completed_rotation_does_not_redownload(tmp_path):
    scheduler, _, clock, market, _, _, _ = fixture(tmp_path)
    scheduler.run_due_once()
    clock[0] += timedelta(minutes=10)
    scheduler.run_due_once()
    response = scheduler.market_intelligence("alice")
    assert response["coverage"]["retained_qualified_symbols"] == 3
    assert response["coverage"]["universe"]["rotation_complete"]
    assert market.get_liquidity_histories.call_count == 2
    clock[0] += timedelta(minutes=10)
    scheduler.run_due_once()
    assert market.get_liquidity_histories.call_count == 2


def test_restart_retains_historical_pool_and_resumes_cursor(tmp_path):
    scheduler, store, clock, _, _, _, _ = fixture(tmp_path)
    scheduler.run_due_once()
    restored = ScannerScheduler(store, scheduler.runner_factory, lambda user: True, scheduler.settings, clock=lambda: clock[0])
    restored.activate_user("alice", tmp_path / "user.sqlite")
    assert restored.market_intelligence("alice")["coverage"]["retained_qualified_symbols"] == 2
    clock[0] += timedelta(minutes=10)
    restored.run_due_once()
    assert restored.market_intelligence("alice")["coverage"]["retained_qualified_symbols"] == 3
    assert restored.market_intelligence("bob")["coverage"]["retained_qualified_symbols"] == 0


def test_live_transition_preserves_historical_pool_but_never_passes_it_to_live_scan(tmp_path):
    scheduler, store, clock, _, broker, _, runners = fixture(tmp_path)
    scheduler.run_due_once()
    saved = deepcopy(store.load("alice")["historical_market_intelligence"])
    clock[0] = NOW.replace(hour=13, minute=30)
    broker.clock.return_value = {"is_open": True}
    runner = runners[0]
    runner.scan = Mock(return_value={"generated_at": clock[0].isoformat(), "candidates": [], "errors": [],
                                    "stage_counts": {"valid_data_count": 2}, "market_intelligence_rows": []})
    assert scheduler.run_due_once()["status"] == "completed"
    runner.scan.assert_called_once_with(["AAA", "BBB", "CCC"], offset=0, now=None)
    assert store.load("alice")["historical_market_intelligence"] == saved
    assert store.load("alice")["market_session"] == "open"
    assert "Waiting for current-session observations" in scheduler.market_intelligence("alice")["message"]
    # Once a genuine current pool is published the historical display yields.
    current = deepcopy(saved["observations"]["AAA"])
    current.update(data_timestamp=clock[0].isoformat(), qualified_at=clock[0].isoformat(), historical=False)
    scheduler.sessions["alice"].state["market_intelligence"] = {
        "session_date": "2026-09-03", "observations": {"AAA": current}}
    assert scheduler.market_intelligence("alice")["display_mode"] == "live"


@pytest.mark.parametrize("defect", ["missing_target", "missing_previous", "duplicate", "too_short", "nan", "negative_volume", "illiquid"])
def test_invalid_missing_and_illiquid_history_cannot_create_rankings(defect):
    frame = history()
    if defect == "missing_target": frame = frame.drop(pd.Timestamp("2026-09-02", tz="UTC"))
    if defect == "missing_previous": frame = frame.drop(pd.Timestamp("2026-09-01", tz="UTC"))
    if defect == "duplicate": frame = pd.concat([frame, frame.tail(1)])
    if defect == "too_short": frame = frame.tail(5)
    if defect == "nan": frame.loc["2026-09-02", "Close"] = float("nan")
    if defect == "negative_volume": frame.loc["2026-09-02", "Volume"] = -1
    if defect == "illiquid": frame["Volume"] = 10
    row, _ = historical_row("AAA", frame, completed_sessions(CALENDAR, NOW), NOW, ScannerSettings().stage_config())
    assert row is None


def test_missing_latest_session_does_not_substitute_older_close_or_advance_page(tmp_path):
    frame = history().drop(pd.Timestamp("2026-09-02", tz="UTC"))
    scheduler, store, _, _, _, _, _ = fixture(tmp_path, frame)
    scheduler.run_due_once()
    state = store.load("alice")["historical_market_intelligence"]
    assert state["observations"] == {}
    assert state["universe"]["next_offset"] == 0
    assert state["partial_failure"]


def test_calendar_holiday_weekend_and_early_close_not_weekday_guesses():
    calendar = [{"date": "2026-11-25", "open": "09:30", "close": "16:00"},
                {"date": "2026-11-27", "open": "09:30", "close": "13:00"}]
    weekend = datetime(2026, 11, 29, 12, tzinfo=timezone.utc)
    sessions = completed_sessions(calendar, weekend)
    assert sessions[-1]["date"] == "2026-11-27"
    assert sessions[-1]["close"].astimezone(timezone.utc).hour == 18
    assert (sessions[-1]["close"] - sessions[-1]["open"]).total_seconds() == 12600


def test_next_open_deadline_shortens_closed_poll_interval(tmp_path):
    scheduler, store, clock, _, _, _, _ = fixture(tmp_path)
    clock[0] = NOW.replace(hour=13, minute=29)
    scheduler.run_due_once()
    assert store.load("alice")["next_broad_at"] == "2026-09-03T13:30:00+00:00"


def test_authenticated_runtime_restore_first_scan_and_today_endpoints(scanner_client, tmp_path, monkeypatch):
    from app import main
    client, _, _, _ = scanner_client
    scheduler, _, _, market, _, _, _ = fixture(tmp_path)
    scheduler.deactivate_user("alice")
    monkeypatch.setattr(main, "scanner_scheduler", scheduler)
    monkeypatch.setattr(main.app.state, "scanner_scheduler", scheduler)
    client.cookies.set("orion_session", "alice")
    assert client.get("/auth/session").status_code == 200
    assert client.get("/scanner/current").json()["status"] == "starting"
    market.get_liquidity_histories.assert_not_called()
    assert scheduler.run_due_once()["status"] == "historical_completed"
    current = client.get("/scanner/current")
    assert current.status_code == 200
    assert current.json()["universe"]["total_symbols"] == 3
    intelligence = client.get("/scanner/market-intelligence")
    assert intelligence.status_code == 200
    assert intelligence.json()["categories"]["most_active"]["last_known"][0]["current_price"] == 104
    assert market.get_liquidity_histories.call_count == 1  # Polling never downloads.


def test_live_daily_cache_cannot_supply_completed_close(tmp_path):
    scheduler, _, _, market, _, _, runners = fixture(tmp_path)
    incomplete = history()
    incomplete.loc["2026-09-02", "Close"] = 101
    market.get_liquidity_histories.side_effect = lambda symbols, **kw: {"histories": {s: incomplete for s in symbols}, "errors": []}
    runners[0].cache.get_liquidity_histories(["AAA", "BBB"])
    market.get_liquidity_histories.side_effect = lambda symbols, **kw: {"histories": {s: history() for s in symbols}, "errors": []}
    scheduler.run_due_once()
    rows = scheduler.market_intelligence("alice")["categories"]["most_active"]["last_known"]
    assert all(row["current_price"] == 104 for row in rows)
    assert market.get_liquidity_histories.call_count == 2


def test_missing_bar_cache_is_evicted_and_retry_can_succeed(tmp_path):
    scheduler, _, clock, market, _, _, _ = fixture(tmp_path, history().drop(pd.Timestamp("2026-09-02", tz="UTC")))
    scheduler.run_due_once()
    market.get_liquidity_histories.side_effect = lambda symbols, **kw: {"histories": {s: history() for s in symbols}, "errors": []}
    clock[0] += timedelta(minutes=10)
    scheduler.run_due_once()
    assert scheduler.market_intelligence("alice")["coverage"]["retained_qualified_symbols"] == 2
