"""Offline category arithmetic, cross-page persistence and read-only API tests."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from app.services import market_intelligence as intelligence
from app.services.market_intelligence import compact_observation, current_categories, merge_observations
from app.services.scanner_settings import ScannerSettings
from app.services.scanner_state_store import ScannerStateStore
from app.services.continuous_scanner import ScannerScheduler
from app.services.staged_market_scanner import ScannerConfig, StagedMarketScanner
from app.services.staged_scanner_adapters import ExistingMarketScannerSource
from test_staged_market_scanner import NOW, screening, context, scan, RecordingSource
from test_staged_scanner_adapters import Market, Broker
from test_continuous_scanner import build
from test_scanner_api import scanner_client


def row(symbol, now=NOW, features=None, **changes):
    screen = screening(data_timestamp=now.isoformat(), **changes)
    ctx = context(features) if features is not None else None
    if ctx:
        ctx["feature_snapshot"]["timestamp"] = now.isoformat()
    return compact_observation(symbol, screen, now, ctx)


def merge(previous=None, rows=(), now=NOW, invalidated=(), universe=None):
    return merge_observations(previous, rows, invalidated=invalidated, now=now,
                              config=ScannerConfig(), universe=universe)


def view(data, now=NOW, **kwargs):
    return current_categories(data, now=now, settings=ScannerSettings(), **kwargs)


def symbols(result, category, group="items"):
    return [r["ticker"] for r in result["categories"][category][group]]


def quote(**changes):
    return {"bid": 99.99, "ask": 100.01, "bid_size": 300, "ask_size": 100,
            "timestamp": NOW.isoformat(), "provider": "alpaca", "feed": "iex",
            "kind": "inferred_quote_pressure", **changes}


def reversion(**changes):
    return {"rsi_14": 30, "return_1m": .002, "return_3m": -.01, "return_5m": -.03,
            "distance_from_vwap": -.02, "atr_14": 1, "realized_volatility": .005, **changes}


def test_all_categories_return_sorted_signed_metrics_and_explicit_semantics():
    rows = [row("GAIN", intraday_return=.1, dollar_volume=500_000_000, relative_volume=4),
            row("LOSS", intraday_return=-.12, dollar_volume=600_000_000, relative_volume=2),
            row("SMALLLOSS", intraday_return=-.01, relative_volume=1),
            row("FLAT", intraday_return=0, relative_volume=1)]
    result = view(merge(rows=rows))
    assert set(result["categories"]) == set(intelligence.CATEGORIES)
    assert symbols(result, "biggest_gainers") == ["GAIN"]
    assert symbols(result, "biggest_losers") == ["LOSS", "SMALLLOSS"]
    assert result["categories"]["biggest_losers"]["items"][0]["ranking_value"] == -12
    assert symbols(result, "most_active")[:2] == ["LOSS", "GAIN"]
    assert symbols(result, "unusual_volume") == ["GAIN", "LOSS"]
    assert "NOT Most Bought" in result["categories"]["most_active"]["semantics"]


def test_cross_page_top_n_keeps_runner_ups_and_replaces_by_symbol_not_page(monkeypatch):
    monkeypatch.setattr(intelligence, "TOP_N", 2)
    data = merge(rows=[row("AAA", intraday_return=.09), row("BBB", intraday_return=.07)])
    later = NOW + timedelta(seconds=60)
    data = merge(data, [row("CCC", later, intraday_return=.08)], later)
    assert symbols(view(data, later), "biggest_gainers") == ["AAA", "CCC"]
    data = merge(data, [row("AAA", later, intraday_return=.001)], later, invalidated=["AAA"])
    assert symbols(view(data, later), "biggest_gainers") == ["CCC", "BBB"]
    assert len(data["observations"]) == 3
    assert data["observations"]["BBB"]["data_timestamp"] == NOW.isoformat()


def test_ties_are_deterministic_and_top_n_bounded():
    data = merge(rows=[row(f"S{i:02}") for i in reversed(range(20))])
    result = view(data)
    assert symbols(result, "most_active") == [f"S{i:02}" for i in range(10)]
    assert len(data["observations"]) == 20


def test_old_pages_are_stale_not_refreshed_by_a_later_page():
    data = merge(rows=[row("OLD", intraday_return=.20)])
    later = NOW + timedelta(seconds=600)
    data = merge(data, [row("NEW", later, intraday_return=.03)], later)
    result = view(data, later)
    assert symbols(result, "biggest_gainers") == ["NEW"]
    assert symbols(result, "biggest_gainers", "last_known") == ["OLD"]
    old = result["categories"]["biggest_gainers"]["last_known"][0]
    assert old["freshness"]["state"] == "stale" and old["freshness"]["price_age_seconds"] == 600


def test_rejected_rescreen_removes_only_that_symbol_and_universe_change_prunes():
    data = merge(rows=[row("AAA"), row("BBB"), row("CCC")])
    data = merge(data, invalidated=["AAA"])
    assert set(data["observations"]) == {"BBB", "CCC"}
    data = merge(data, universe={"CCC"})
    assert set(data["observations"]) == {"CCC"}


def test_out_of_order_observation_does_not_overwrite_newer_input():
    later = NOW + timedelta(seconds=20)
    data = merge(rows=[row("AAA", later, intraday_return=.08)], now=later)
    data = merge(data, [row("AAA", intraday_return=.1)], later, invalidated=["AAA"])
    assert data["observations"]["AAA"]["intraday_return"] == .08
    assert data["observations"]["AAA"]["data_timestamp"] == later.isoformat()


@pytest.mark.parametrize("fields", [
    {"price": 1}, {"average_dollar_volume": 100_000}, {"dollar_volume": 20},
    {"spread_pct": .31}, {"history_sessions": 2}, {"liquidity_score": None},
    {"relative_volume": float("nan"), "intraday_return": None},
])
def test_missing_or_illiquid_inputs_never_create_category_values(fields):
    result, _, _ = scan({"BAD": screening(**fields)})
    data = merge(rows=result["market_intelligence_rows"])
    ranked = view(data)
    assert not ranked["categories"]["biggest_gainers"]["items"]
    assert not ranked["categories"]["unusual_volume"]["items"]
    if "relative_volume" not in fields:
        assert not ranked["categories"]["most_active"]["items"]


def test_quiet_liquid_stock_is_ranked_without_features_model_or_additional_downloads():
    result, source, analyzer = scan({"QUIET": screening(relative_volume=1, intraday_return=0)})
    assert len(source.screen_batches) == 1
    assert source.feature_batches == analyzer.calls == []
    assert symbols(view(merge(rows=result["market_intelligence_rows"])), "most_active") == ["QUIET"]


def test_categories_work_when_no_fitted_model_exists_and_do_not_add_calls():
    source = RecordingSource({"MOVE": screening()})
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(args[0])
        return {"results": [], "model_calls": 0, "unavailable": []}
    result = StagedMarketScanner(source, unavailable).scan_market(now=NOW)
    assert result["candidates"] == [] and result["stage_counts"]["model_evaluations"] == 0
    assert calls == ["MOVE"]
    assert len(source.screen_batches) == len(source.feature_batches) == 1
    assert symbols(view(merge(rows=result["market_intelligence_rows"])), "momentum_leaders") == ["MOVE"]


def test_momentum_and_mean_reversion_use_existing_features_not_raw_loser_rank():
    rising = {"return_1m": .003, "return_3m": .006, "return_5m": .01, "relative_strength_market": .005}
    reverting = reversion()
    falling = {**reverting, "return_1m": -.01}
    rows = [row("MOM", features=rising), row("REVERT", features=reverting, intraday_return=-.1),
            row("FALL", features=falling, intraday_return=-.2), row("LOSS", intraday_return=-.3)]
    result = view(merge(rows=rows))
    assert symbols(result, "momentum_leaders") == ["MOM"]
    assert result["categories"]["momentum_leaders"]["items"][0]["ranking_value"] == 100
    assert symbols(result, "potential_bargains") == ["REVERT"]
    candidate = result["categories"]["potential_bargains"]["items"][0]
    assert candidate["ranking_value"] == pytest.approx((99.5 / .98 - 99.5) / 1)
    assert candidate["mean_reversion_evidence"]["vwap_distance_return_volatility"] == 4
    assert candidate["trade_recommendation"] is False
    assert candidate["freshness"]["state"] == "delayed"
    assert symbols(result, "biggest_losers")[0] == "LOSS"


@pytest.mark.parametrize("changes", [{"return_1m": 0}, {"rsi_14": 36}, {"rsi_14": -1},
                                      {"distance_from_vwap": 0}, {"distance_from_vwap": None},
                                      {"atr_14": None}, {"atr_14": 0}, {"atr_14": 10},
                                      {"realized_volatility": None}, {"realized_volatility": 0},
                                      {"realized_volatility": .02}, {"realized_volatility": float("nan")},
                                      {"return_5m": None}, {"return_5m": .01}, {"distance_from_vwap": -.001}])
def test_mean_reversion_requires_oversold_extension_and_actual_reversal(changes):
    features = reversion(**changes)
    assert symbols(view(merge(rows=[row("NO", features=features)])), "potential_bargains") == []


def test_reversion_uses_feature_price_not_newer_live_price_and_ranks_dislocation():
    weak = row("WEAK", features=reversion(), price=110)
    strong = row("STRONG", features=reversion(distance_from_vwap=-.03), price=90)
    result = view(merge(rows=[weak, strong]))
    assert symbols(result, "potential_bargains") == ["STRONG", "WEAK"]
    evidence = result["categories"]["potential_bargains"]["items"][0]["mean_reversion_evidence"]
    assert evidence["feature_reference_price"] == 99.5
    assert evidence["feature_vwap"] == pytest.approx(99.5 / .97)
    assert evidence["vwap_distance_atr"] == pytest.approx(99.5 / .97 - 99.5)
    assert "not a z-score" in evidence["meaning"]


@pytest.mark.parametrize("price", [None, 0, -1, float("inf")])
def test_missing_or_invalid_historical_feature_price_excludes_bargain(price):
    item = row("BAD", features=reversion())
    item["feature_reference_price"] = price
    assert not symbols(view(merge(rows=[item])), "potential_bargains")


def test_legacy_observation_without_statistics_is_not_promoted_to_bargain():
    item = row("OLD", features=reversion())
    item["features"].pop("atr_14")
    item["features"].pop("realized_volatility")
    assert not symbols(view(merge(rows=[item])), "potential_bargains")


@pytest.mark.parametrize("atr_multiple,vol_multiple,qualifies", [(1.5, 2, True), (1.499, 2, False), (1.5, 1.999, False)])
def test_mean_reversion_normalized_dislocation_boundaries(atr_multiple, vol_multiple, qualifies):
    item = row("BOUND", features=reversion(atr_14=(99.5 / .98 - 99.5) / atr_multiple,
                                          realized_volatility=.02 / vol_multiple))
    assert bool(symbols(view(merge(rows=[item])), "potential_bargains")) is qualifies


def test_category_freshness_is_specific_to_quote_or_feature_timestamp():
    item = row("AAA", features=reversion(), quote_evidence=quote())
    item["feature_timestamp"] = (NOW - timedelta(seconds=1201)).isoformat()
    item["quote_evidence"]["timestamp"] = (NOW - timedelta(seconds=121)).isoformat()
    result = view(merge(rows=[item]))
    assert symbols(result, "most_active") == ["AAA"]
    assert not symbols(result, "buy_pressure")
    assert symbols(result, "buy_pressure", "last_known") == ["AAA"]
    assert symbols(result, "potential_bargains", "last_known") == ["AAA"]


def test_pressure_uses_signed_displayed_sizes_and_labels_inference():
    rows = [row("BID", quote_evidence=quote()), row("ASK", quote_evidence=quote(bid_size=100, ask_size=300))]
    result = view(merge(rows=rows))
    for key, symbol, sign in [("buy_pressure", "BID", 1), ("sell_pressure", "ASK", -1)]:
        assert symbols(result, key) == [symbol]
        item = result["categories"][key]["items"][0]
        assert item["ranking_value"] == sign * .5
        assert item["pressure_kind"] == "inferred_quote_pressure"
        assert item["quote_evidence"]["feed"] == "iex"
        assert "inferred quote pressure" in result["categories"][key]["label"]


@pytest.mark.parametrize("changes", [{"bid_size": None}, {"bid_size": -1}, {"ask_size": 0},
                                      {"bid_size": float("nan")}, {"bid": 100.02},
                                      {"ask": 99.99}, {"timestamp": None}, {"kind": "volume_guess"}])
def test_invalid_pressure_evidence_cannot_fill_current_pressure_categories(changes):
    data = merge(rows=[row("BAD", quote_evidence=quote(**changes))])
    json.dumps(data, allow_nan=False)
    result = view(data)
    assert not symbols(result, "buy_pressure") and not symbols(result, "sell_pressure")


def test_adapter_retains_raw_quote_provenance_but_does_not_reuse_stale_quote():
    broker, market = Broker(("MOVE",)), Market()
    broker.data["MOVE"]["latestQuote"]["bs"] = 300
    source = ExistingMarketScannerSource(market, broker, "test")
    screen = source.load_screening_batch(["MOVE"], now=NOW)["rows"]["MOVE"]
    assert screen["quote_evidence"]["bid_size"] == 300
    assert screen["quote_evidence"]["timestamp"] == broker.data["MOVE"]["latestQuote"]["t"]
    assert screen["session_return_source"] == "alpaca_previous_daily_close"
    broker.data["MOVE"]["latestQuote"]["t"] = (NOW - timedelta(seconds=121)).isoformat()
    screen = source.load_screening_batch(["MOVE"], now=NOW)["rows"]["MOVE"]
    assert screen["quote_evidence"] is None
    assert len(broker.snapshot_calls) == len(market.daily_calls) == 2
    assert not market.minute_calls


def test_session_rollover_and_capacity_limits_are_explicit(monkeypatch):
    monkeypatch.setattr(intelligence, "MAX_SYMBOLS", 2)
    data = merge(rows=[row("AAA"), row("BBB"), row("CCC")])
    assert len(data["observations"]) == 2 and data["capacity_evictions"] == 1
    next_day = NOW + timedelta(days=1)
    assert view(data, next_day)["coverage"]["retained_qualified_symbols"] == 0
    assert merge(data, now=next_day)["observations"] == {}


def test_scheduler_persists_cross_page_rows_and_restart_never_marks_them_current(tmp_path):
    scheduler, runner, clock, store, _ = build(tmp_path)
    original = runner.scan
    def scan_page(*args, **kwargs):
        result = original(*args, **kwargs)
        result["market_intelligence_rows"] = [row(symbol, clock()) for symbol in runner.calls[-1]]
        result["market_observed_symbols"] = runner.calls[-1]
        return result
    runner.scan = scan_page
    scheduler.run_scan_cycle("alice", now=clock())
    first = scheduler.market_intelligence("alice")
    assert symbols(first, "most_active") == ["AAA", "BBB"]
    clock.advance(60)
    scheduler.run_scan_cycle("alice", now=clock())
    assert symbols(scheduler.market_intelligence("alice"), "most_active") == ["AAA", "BBB", "CCC", "DDD"]
    assert store.load("alice")["market_intelligence"]["observations"]["AAA"]["data_timestamp"] == NOW.isoformat()
    restored = ScannerScheduler(ScannerStateStore(store.path), lambda *_: runner, lambda _: True, scheduler.settings, clock=clock)
    result = restored.market_intelligence("alice")
    assert not symbols(result, "most_active")
    assert len(symbols(result, "most_active", "last_known")) == 4
    assert result["restored_unverified"] is True
    assert not symbols(restored.market_intelligence("bob"), "most_active", "last_known")


def test_partial_scan_retains_unknown_rows_but_invalidates_observed_rejections():
    data = merge(rows=[row("AAA"), row("BBB")])
    data = merge(data, [], invalidated=["AAA"])
    assert set(data["observations"]) == {"BBB"}
    assert data["observations"]["BBB"]["data_timestamp"] == NOW.isoformat()
    assert not symbols(view(data, force_stale=True), "most_active")


def test_endpoint_is_authenticated_user_isolated_and_read_only(scanner_client):
    client, scheduler, runner, clock = scanner_client
    assert client.get("/scanner/market-intelligence").status_code == 401
    scheduler.sessions["alice"].state["market_intelligence"] = merge(rows=[row("AAA")])
    count = len(runner.calls)
    client.cookies.set("orion_session", "alice")
    for _ in range(3):
        response = client.get("/scanner/market-intelligence")
        assert response.status_code == 200
        assert symbols(response.json(), "most_active") == ["AAA"]
        assert "universe" in response.json()["coverage"]
    assert len(runner.calls) == count
    assert client.post("/scanner/market-intelligence", headers={"X-CSRF-Token": "csrf"}).status_code == 405
    client.cookies.set("orion_session", "bob")
    assert symbols(client.get("/scanner/market-intelligence?user_id=alice").json(), "most_active") == []


def test_reading_categories_does_not_mutate_persisted_observations():
    data = merge(rows=[row("AAA", quote_evidence=quote())])
    original = deepcopy(data)
    view(data, NOW + timedelta(seconds=121))
    assert data == original


def test_active_refresh_keeps_cross_page_pool_and_last_broad_time_without_model_results(tmp_path):
    scheduler, runner, clock, store, _ = build(tmp_path)
    original = runner.scan
    def no_model_page(*args, **kwargs):
        result = original(*args, **kwargs)
        result["candidates"] = []
        result["market_intelligence_rows"] = [row(symbol, clock()) for symbol in runner.calls[-1]]
        result["market_observed_symbols"] = runner.calls[-1]
        return result
    runner.scan = no_model_page
    scheduler.run_scan_cycle("alice", now=clock())
    assert scheduler.current_state("alice")["top_candidates"] == []
    assert symbols(scheduler.market_intelligence("alice"), "most_active") == ["AAA", "BBB"]
    broad_at = clock().isoformat()
    # Active work updates its symbols, not the broad rotation or last-broad time.
    clock.advance(120)
    scheduler.run_scan_cycle("alice", "active", now=clock())
    assert scheduler.market_intelligence("alice")["coverage"]["last_broad_scan_at"] == broad_at
    assert store.load("alice")["market_intelligence"]["observations"]["AAA"]["data_timestamp"] == clock().isoformat()
    runner.fail = True
    clock.advance(120)
    scheduler.run_scan_cycle("alice", "active", now=clock())
    result = scheduler.market_intelligence("alice")
    assert result["partial_failure"] is True
    assert not symbols(result, "most_active")
    assert symbols(result, "most_active", "last_known") == ["AAA", "BBB"]


@pytest.mark.parametrize("age,expected", [(120, "current"), (121, "stale")])
def test_price_freshness_boundary_and_missing_pressure_timestamp(age, expected):
    data = merge(rows=[row("AAA", quote_evidence=quote(timestamp=None))])
    result = view(data, NOW + timedelta(seconds=age))
    assert result["categories"]["most_active"]["freshness"] == expected
    assert result["categories"]["buy_pressure"]["freshness"] == "unavailable"


def test_prior_session_technical_evidence_cannot_be_a_current_reversion_setup():
    item = row("AAA", features=reversion())
    item["feature_timestamp"] = (NOW - timedelta(days=1)).isoformat()
    result = view(merge(rows=[item]))
    assert symbols(result, "potential_bargains") == symbols(result, "potential_bargains", "last_known") == []
