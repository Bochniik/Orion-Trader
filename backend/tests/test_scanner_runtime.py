"""Provider pacing/cache and existing staged-core integration without network."""
from datetime import datetime, timedelta, timezone
from threading import Event

import pandas as pd
import pytest

from app.services import staged_scanner_adapters
from app.services.scanner_runtime import ExistingScannerRunner, ScannerCancelled, ScannerProviderCache
from app.services.scanner_settings import ScannerSettings
from app.services.staged_market_scanner import StagedMarketScanner
from test_staged_scanner_adapters import Broker, Market, fitted_fixture
from test_staged_market_scanner import RecordingSource, RecordingAnalyzer, screening


NOW = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)


class SmallBatchMarket(Market):
    def get_liquidity_histories(self, symbols, *, period, chunk_size):
        assert len(symbols) == chunk_size <= 10
        return super().get_liquidity_histories(symbols, period=period)

    def get_intraday_histories(self, symbols, *, period, interval, chunk_size):
        assert len(symbols) == chunk_size <= 10
        return super().get_intraday_histories(symbols, period=period, interval=interval)


def cache_fixture():
    clock, waits, cancel = [0.0], [], Event()

    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds
        return cancel.is_set()

    market, broker = SmallBatchMarket(), Broker(("MOVE",))
    cache = ScannerProviderCache(market, broker, ScannerSettings(), cancel, clock=lambda: clock[0], wait=wait, wall_clock=lambda: NOW)
    return cache, market, broker, clock, waits, cancel


def test_reuses_daily_and_minute_history_without_rewriting_source_timestamps():
    cache, market, _, clock, _, _ = cache_fixture()
    first = cache.get_intraday_histories(["MOVE"])["histories"]["MOVE"]
    cache.get_liquidity_histories(["MOVE"])
    clock[0] += 20
    second = cache.get_intraday_histories(["MOVE"])["histories"]["MOVE"]
    cache.get_liquidity_histories(["MOVE"])
    assert market.minute_calls == market.daily_calls == [["MOVE"]]
    pd.testing.assert_frame_equal(first, second)
    second.iloc[-1, second.columns.get_loc("Close")] = 99999
    third = cache.get_intraday_histories(["MOVE"])["histories"]["MOVE"]
    pd.testing.assert_frame_equal(first, third)
    clock[0] += 61
    cache.get_intraday_histories(["MOVE"])
    assert len(market.minute_calls) == 2


def test_provider_groups_and_request_spacing_are_bounded():
    cache, market, _, _, waits, _ = cache_fixture()
    symbols = [f"S{i:03d}" for i in range(25)]
    loaded = cache.get_liquidity_histories(symbols)
    assert set(loaded["histories"]) == set(symbols)
    assert [len(group) for group in market.daily_calls] == [10, 10, 5]
    assert waits == [1, 1]


def test_universe_and_clock_are_cached_but_live_snapshots_are_not():
    cache, _, broker, _, _, _ = cache_fixture()
    counts = {"assets": 0, "clock": 0}
    assets, clock = broker.assets, broker.clock

    def load_assets(user):
        counts["assets"] += 1
        return assets(user)

    def load_clock(user):
        counts["clock"] += 1
        return clock(user)

    broker.assets, broker.clock = load_assets, load_clock
    for _ in range(2):
        cache.assets("alice")
        cache.clock_status("alice")
        cache.snapshots("alice", ["MOVE"])
    assert counts == {"assets": 1, "clock": 1}
    assert len(broker.snapshot_calls) == 2


def test_cancelled_cache_never_starts_another_provider_request():
    cache, market, _, _, _, cancel = cache_fixture()
    cancel.set()
    with pytest.raises(ScannerCancelled):
        cache.get_liquidity_histories(["MOVE"])
    assert market.daily_calls == []


def test_staged_core_honors_cancellation_between_batches():
    cancel = Event()
    source, analyzer = RecordingSource({"MOVE": screening()}), RecordingAnalyzer()
    original = source.load_screening_batch

    def mark_cancelled(*args, **kwargs):
        result = original(*args, **kwargs)
        cancel.set()
        return result

    def checkpoint():
        if cancel.is_set():
            raise ScannerCancelled()

    source.load_screening_batch = mark_cancelled
    with pytest.raises(ScannerCancelled):
        StagedMarketScanner(source, analyzer, check_cancelled=checkpoint).scan_market(now=NOW)
    assert source.feature_batches == analyzer.calls == []


def test_actual_runtime_uses_existing_stages_and_only_fifteen_model_calls(monkeypatch):
    symbols = [f"S{i:03d}" for i in range(250)]
    market, broker = SmallBatchMarket(), Broker(symbols)
    runner = ExistingScannerRunner(market, broker, "alice", fitted_fixture, ScannerSettings(), Event())
    clock = [0.0]
    runner.cache.clock = lambda: clock[0]
    runner.cache.wall_clock = lambda: NOW

    def wait(seconds):
        clock[0] += seconds
        return False

    runner.cache.wait = wait
    calls, original = [], staged_scanner_adapters.build_live_prediction

    def record(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(staged_scanner_adapters, "build_live_prediction", record)
    runner.prepare()
    universe = runner.universe()
    result = runner.scan(universe["tickers"], now=NOW)
    assert result["stage_counts"]["screened_count"] == 250
    assert result["stage_counts"]["activity_candidates"] == 100
    assert result["stage_counts"]["fast_candidates"] == 30
    assert len(calls) == result["stage_counts"]["model_evaluations"] == 15
    assert len(result["candidates"]) == 10
    assert len(result["active_candidates"]) == 30
    assert all(row["final_decision"] == "NO_TRADE" for row in result["candidates"])
    assert len(market.daily_calls) == 25 and len(market.minute_calls) == 11
    assert len(broker.snapshot_calls) == 3


def test_provider_failure_is_not_cached_as_success():
    cache, market, _, _, _, _ = cache_fixture()
    original = market.get_intraday_histories
    calls = []

    def temporary(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("synthetic")
        return original(*args, **kwargs)

    market.get_intraday_histories = temporary
    first = cache.get_intraday_histories(["MOVE"])
    assert first["errors"] and first["histories"] == {}
    assert "MOVE" in cache.get_intraday_histories(["MOVE"])["histories"]
