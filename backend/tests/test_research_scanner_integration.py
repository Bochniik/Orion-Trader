from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock

import pandas as pd

from app import main
from app.services.professional_scanner import PROFILES
from app.services.opportunity_journal import OpportunityJournal
from app.services.staged_scanner_adapters import ExistingMarketScannerSource
from app.services.staged_market_scanner import ScannerConfig
from app.services.research_scanner_adapter import daily_inputs
from test_professional_scanner import bars, screen, setup, NOW
from test_scanner_api import scanner_client


def clients():
    market, broker = Mock(), Mock()
    daily = bars("swing")
    dates = [stamp.date().isoformat() for stamp in daily.index]
    raw = daily.copy()
    raw.index = pd.to_datetime(dates, utc=True)
    broker.research_calendar.return_value = [{"date": day, "open": "09:30", "close": "16:00"} for day in dates]
    market.get_price_history.return_value = raw
    market.get_intraday_histories.return_value = {"histories": {}, "errors": []}
    return market, broker


def test_daily_adapter_normalizes_calendar_close_and_loads_benchmark_only_once():
    market, broker = clients()
    result, calendar, errors = daily_inputs(market, broker, "alice", ["TEST", "SPY"], NOW)
    assert not errors
    assert market.get_price_history.call_count == 2
    assert result["TEST"].index[-1].isoformat() == "2026-09-02T20:00:00+00:00"
    assert calendar[-1]["open"].endswith("09:30:00-04:00")


def test_production_source_saves_all_horizons_without_a_model_and_bounds_finalists(tmp_path):
    market, broker = clients()
    journal = OpportunityJournal(tmp_path / "journal.sqlite")
    config = ScannerConfig(universe_limit=2, activity_limit=2, fast_limit=2, analysis_limit=1, return_limit=1)
    source = ExistingMarketScannerSource(market, broker, "alice", config, research_enabled=True, journal=journal)
    minute = bars()
    screens = {s: screen(minute) for s in ("TEST", "LOWER")}
    screens["LOWER"]["average_dollar_volume"] = 30_000_000
    contexts = {"TEST": {"research_history": minute, "research_benchmark": minute}}
    result = source.build_research_setups(screens, contexts, [], now=NOW)
    assert {row["horizon"] for row in result["items"]} == set(PROFILES)
    assert all(row["confidence"] is None and row["setup_id"] for row in result["items"])
    assert len(journal.history()) == 3
    assert result["coverage"]["capacity_excluded"] == 1
    assert market.get_price_history.call_count == 2  # stock + shared SPY, not once per horizon
    source.build_research_setups(screens, contexts, [], now=NOW)
    assert len(journal.history()) == 3


def test_pending_outcomes_revisited_even_when_stock_has_no_current_setup(tmp_path):
    market, broker = clients()
    journal = OpportunityJournal(tmp_path / "journal.sqlite")
    journal.save(setup())
    source = ExistingMarketScannerSource(market, broker, "alice", research_enabled=True, journal=journal)
    source.build_research_setups({}, {}, [], now=NOW + timedelta(hours=2))
    assert journal.history()[0]["pending_reason"] == "invalid_or_missing_observations"
    assert market.get_intraday_histories.call_args.args[0] == ["TEST"]


def test_user_scoped_history_api_never_creates_market_download(scanner_client, monkeypatch):
    client, scheduler, runner, _ = scanner_client
    client.cookies.set("orion_session", "alice")
    alice = OpportunityJournal(main.auth_store.user_database("alice"))
    alice.save(setup())
    before = deepcopy(runner.calls)
    assert len(client.get("/scanner/opportunities/history").json()["items"]) == 1
    assert client.get("/scanner/opportunities/analytics").json()["overall"]["samples"] == 0
    assert client.get("/scanner/opportunities").status_code == 200
    client.cookies.set("orion_session", "bob")
    assert client.get("/scanner/opportunities/history").json()["items"] == []
    assert runner.calls == before
    client.cookies.clear()
    assert client.get("/scanner/opportunities/history").status_code == 401


def test_ai_receives_saved_numbers_not_client_created_signal(scanner_client, monkeypatch):
    from app.services import orion_ai_service
    client, _, _, _ = scanner_client
    client.cookies.set("orion_session", "alice")
    client.headers["X-CSRF-Token"] = "csrf"
    journal = OpportunityJournal(main.auth_store.user_database("alice"))
    key = journal.save(setup())
    original = journal.get(key)
    explain = Mock(return_value={"explanation": {"summary": "Unvalidated research only."}})
    monkeypatch.setattr(orion_ai_service, "explain_predictive_result", explain)
    response = client.post(f"/scanner/opportunities/{key}/explain", json={"confidence": 99})
    assert response.status_code == 200
    assert explain.call_args.args[0]["confidence"]["value"] is None
    assert explain.call_args.args[0]["P_UP"] is None
    assert journal.get(key) == original
    client.cookies.set("orion_session", "bob")
    assert client.post(f"/scanner/opportunities/{key}/explain").status_code == 404


def test_research_rankings_accumulate_across_pages_but_old_quotes_are_stale(tmp_path):
    from test_continuous_scanner import build
    scheduler, runner, clock, _, _ = build(tmp_path)
    clock.now = NOW
    original_scan = runner.scan
    def scan(symbols, offset=0, now=None):
        result = original_scan(symbols, offset=offset, now=now)
        row = setup()
        row.update(ticker=symbols[offset], data_timestamp=clock().isoformat(), feature_timestamp=clock().isoformat())
        result["research_setups"] = {"items": [row], "evaluated_keys": [row["ticker"]+":day"]}
        return result
    runner.scan = scan
    scheduler.run_scan_cycle("alice", now=clock())
    assert scheduler.opportunity_state("alice")["groups"]["day"][0]["ticker"] == "AAA"
    clock.advance(600)
    scheduler.run_scan_cycle("alice", now=clock())
    result = scheduler.opportunity_state("alice")
    assert result["groups"]["day"][0]["ticker"] == "CCC"
    assert result["last_known"][0]["ticker"] == "AAA"
    assert len(scheduler.sessions["alice"].state["research_setups"]) == 2


def test_pending_daily_plans_cannot_crowd_out_due_intraday_work(tmp_path):
    journal = OpportunityJournal(tmp_path / "pending.sqlite")
    journal.save(setup())
    long = setup("long_term")
    long["ticker"] = "LONG"
    journal.save(long)
    assert journal.pending_symbols(now=NOW + timedelta(minutes=30)) == []
    assert journal.pending_symbols(now=NOW + timedelta(hours=2)) == ["TEST"]
