"""Deterministic scheduler/state tests: no network and no real sleeping."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

import pytest

from app.services.continuous_scanner import ScannerScheduler
from app.services.scanner_settings import ScannerSettings
from app.services.scanner_state_store import ScannerStateStore


NOW = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def settings(**overrides):
    return replace(ScannerSettings(), page_size=2, activity_limit=2, fast_limit=2,
                   full_analysis_limit=2, result_limit=1, active_limit=2, **overrides)


def candidate(symbol, now, **overrides):
    return {"ticker": symbol, "current_price": 100, "model_reference_price": 100,
            "model_direction": "UP", "probability_up": .73, "probability_down": .17,
            "probability_neutral": .10, "directional_confidence": 73,
            "final_decision": "NO_TRADE", "actionable": False, "expected_horizon": "5m",
            "opportunity_score": 90, "activity_score": 100, "fast_signal_score": 100,
            "liquidity_score": 95, "relative_volume": 3, "dollar_volume": 250_000_000,
            "provider": "mock_alpaca", "feed": "iex", "feature_provider": "mock_yahoo",
            "data_timestamp": now.isoformat(), "feature_timestamp": now.isoformat(),
            "delayed": True, "setup_tags": ["momentum_candidate"], "warnings": [], **overrides}


class FakeRunner:
    provider = {"snapshots": "mock_alpaca", "features": "mock_yahoo", "feed": "iex", "feature_feed_delayed": True}

    def __init__(self, clock, symbols=None):
        self.clock = clock
        self.symbols = symbols if symbols is not None else ["AAA", "BBB", "CCC", "DDD", "EEE"]
        self.calls, self.universe_calls, self.prepare_calls = [], 0, 0
        self.fail, self.empty, self.partial = False, False, False
        self.qualifiers = None
        self.modifications = {}
        self.entered = self.release = None

    def prepare(self):
        self.prepare_calls += 1

    def universe(self):
        self.universe_calls += 1
        return {"tickers": self.symbols, "source": "mock_assets"}

    def scan(self, symbols, *, offset=0, now=None):
        selected = symbols[offset:offset + 2]
        self.calls.append(list(selected))
        if self.entered:
            self.entered.set()
            assert self.release.wait(2), "test must release its synthetic blocking provider"
        if self.fail:
            raise TimeoutError("secret-provider-token must never be logged or returned")
        rows = [] if self.empty else [candidate(s, self.clock(), **self.modifications) for s in selected
                                     if self.qualifiers is None or s in self.qualifiers]
        return {"generated_at": self.clock().isoformat(), "candidates": rows,
                "active_candidates": deepcopy(rows), "partial_failure": self.partial,
                "errors": ["synthetic failure"] if self.partial else [],
                "stage_counts": {"universe_count": len(symbols), "screened_count": len(selected),
                                 "fully_analyzed": len(rows), "returned": len(rows)},
                "exclusion_counts": {"liquidity": len(selected) - len(rows)},
                "capacity_exclusions": {}, "unavailable_analyses": []}


def build(tmp_path, config=None):
    clock, connected = Clock(), {"alice": True, "bob": True}
    runner = FakeRunner(clock)
    store = ScannerStateStore(tmp_path / "scanner.db")
    scheduler = ScannerScheduler(store, lambda *_: runner, lambda user: connected.get(user, False),
                                 config or settings(), clock=clock)
    scheduler.activate_user("alice", tmp_path / "alice.db")
    return scheduler, runner, clock, store, connected


def test_service_starts_and_stops_cleanly_without_connected_users(tmp_path):
    scheduler = ScannerScheduler(ScannerStateStore(tmp_path / "scanner.db"),
                                 lambda *_: pytest.fail("No provider without an activated user"), lambda _: False)
    assert scheduler.start() is True
    assert scheduler.thread.is_alive()
    assert scheduler.start() is True
    assert scheduler.stop() is True
    assert not scheduler.thread.is_alive()


def test_activated_service_automatically_runs_its_startup_scan(tmp_path):
    scheduler, runner, _, store, _ = build(tmp_path)
    published = Event()
    save = store.save

    def signal_save(*args):
        save(*args)
        published.set()

    store.save = signal_save
    try:
        assert scheduler.start() is True
        assert published.wait(2)
        assert scheduler.current_state("alice")["scanner_running"] is True
        assert runner.calls == [["AAA", "BBB"]]
    finally:
        assert scheduler.stop() is True


def test_shutdown_drains_inflight_request_without_any_late_publication(tmp_path):
    scheduler, runner, _, store, _ = build(tmp_path)
    runner.entered, runner.release = Event(), Event()
    assert scheduler.start() is True
    assert runner.entered.wait(2)
    try:
        assert scheduler.stop(timeout=0) is False
        assert scheduler.run_scan_cycle("alice")["status"] == "busy"
    finally:
        runner.release.set()
        assert scheduler.stop(timeout=2) is True
    assert store.load("alice") is None
    assert runner.calls == [["AAA", "BBB"]]


def test_background_loop_survives_provider_failure_and_recovers_on_next_due_cycle(tmp_path):
    scheduler, runner, clock, store, _ = build(tmp_path)
    runner.fail = True
    published, save = Event(), store.save

    def signal_save(*args):
        save(*args)
        published.set()

    store.save = signal_save
    try:
        scheduler.start()
        assert published.wait(2)
        assert scheduler.thread.is_alive()
        assert scheduler.current_state("alice")["diagnostics"]["last_failure"]
        published.clear()
        runner.fail = False
        clock.advance(600)
        scheduler.wake.set()
        assert published.wait(2)
        assert scheduler.current_state("alice")["status"] == "ready"
        assert len(runner.calls) == 2
    finally:
        assert scheduler.stop() is True


def test_disabled_configuration_starts_no_thread_or_provider(tmp_path):
    scheduler, runner, _, _, _ = build(tmp_path, settings(enabled=False))
    assert scheduler.start() is False
    assert scheduler.thread is None
    assert runner.calls == []
    assert scheduler.current_state("alice")["status"] == "disabled"


def test_manual_first_page_next_page_final_page_and_wrap(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    assert scheduler.thread is None
    for expected_page in (["AAA", "BBB"], ["CCC", "DDD"], ["EEE"], ["AAA", "BBB"]):
        assert scheduler.run_scan_cycle("alice", now=clock())["status"] == "completed"
        assert runner.calls[-1] == expected_page
        rotation = scheduler.current_state("alice")["universe"]
        if expected_page == ["EEE"]:
            assert rotation["total_symbols"] == rotation["symbols_scanned_this_cycle"] == 5
            assert rotation["pages_completed"] == 3
            assert rotation["last_full_rotation"] == clock().isoformat()
            assert rotation["next_offset"] == 0
        clock.advance(600)
    rotation = scheduler.current_state("alice")["universe"]
    assert rotation["current_page"] == rotation["pages_completed"] == 1
    assert rotation["symbols_scanned_this_cycle"] == 2


def test_universe_change_resets_rotation_and_removes_delisted_active_names(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    old = scheduler.current_state("alice")["universe"]["fingerprint"]
    runner.symbols = ["ZZZ"]
    clock.advance(600)
    scheduler.run_scan_cycle("alice", now=clock())
    state = scheduler.current_state("alice")
    assert runner.calls[-1] == ["ZZZ"]
    assert state["universe"]["total_symbols"] == 1
    assert state["universe"]["fingerprint"] != old
    assert [r["ticker"] for r in state["active_candidates"]] == ["ZZZ"]


def test_rotation_normalizes_universe_like_the_staged_core(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    runner.symbols = [" bbb ", "BBB", "CCC", "BAD/TICKER", None, 123]
    scheduler.run_scan_cycle("alice", now=clock())
    assert runner.calls == [["BBB", "CCC"]]
    assert scheduler.current_state("alice")["universe"]["total_symbols"] == 2


def test_active_members_enter_and_are_bounded(tmp_path):
    scheduler, _, clock, _, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    state = scheduler.current_state("alice")
    assert state["active_candidate_count"] == 2
    assert {r["ticker"] for r in state["active_candidates"]} == {"AAA", "BBB"}
    assert state["active_candidates"][0]["inactive_cycles"] == 0
    assert len(state["top_candidates"]) == 1


def test_inactive_candidates_leave_after_three_unsuccessful_qualifications(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    runner.empty = True
    for attempt in range(3):
        clock.advance(120)
        scheduler.run_scan_cycle("alice", "active", now=clock())
        assert scheduler.current_state("alice")["active_candidate_count"] == (2 if attempt < 2 else 0)


def test_expired_active_candidates_are_not_refreshed_or_returned(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    clock.advance(1800)
    before = runner.prepare_calls
    assert scheduler.run_scan_cycle("alice", "active", now=clock())["status"] == "no_active_candidates"
    assert runner.prepare_calls == before
    assert scheduler.current_state("alice")["active_candidate_count"] == 0


def test_separate_schedules_refresh_active_without_reloading_universe(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    assert scheduler.run_due_once(now=clock())["mode"] == "broad"
    broad_calls = runner.universe_calls
    clock.advance(119)
    assert scheduler.run_due_once(now=clock())["status"] == "idle"
    clock.advance(1)
    assert scheduler.run_due_once(now=clock())["mode"] == "active"
    assert runner.universe_calls == broad_calls
    assert runner.calls[-1] == ["AAA", "BBB"]
    clock.advance(480)
    assert scheduler.run_due_once(now=clock())["mode"] == "broad"
    assert runner.calls[-1] == ["CCC", "DDD"]


def test_no_immediate_duplicate_active_scan_after_broad_cycle(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    scheduler.run_due_once(now=clock())
    assert scheduler.run_scan_cycle("alice", "active", now=clock())["status"] == "rate_limited"
    assert scheduler.run_due_once(now=clock())["status"] == "idle"
    assert len(runner.calls) == 1


def test_overlap_is_prevented_and_state_get_does_not_wait_for_provider(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    runner.entered, runner.release = Event(), Event()
    outcomes = []
    worker = Thread(target=lambda: outcomes.append(scheduler.run_scan_cycle("alice", now=clock())))
    worker.start()
    assert runner.entered.wait(2)
    try:
        assert scheduler.current_state("alice")["cycle_running"] is True
        assert scheduler.run_scan_cycle("alice", "active", now=clock())["status"] == "busy"
        assert scheduler.run_scan_cycle("alice", now=clock())["status"] == "busy"
    finally:
        runner.release.set()
        worker.join(2)
    assert not worker.is_alive() and outcomes[0]["status"] == "completed"
    assert len(runner.calls) == 1


def test_cancelled_provider_operation_cannot_commit_or_release_capacity_early(tmp_path):
    scheduler, runner, clock, store, _ = build(tmp_path)
    runner.entered, runner.release = Event(), Event()
    outcomes = []
    worker = Thread(target=lambda: outcomes.append(scheduler.run_scan_cycle("alice", now=clock())))
    worker.start()
    assert runner.entered.wait(2)
    scheduler.deactivate_user("alice")
    scheduler.activate_user("alice", tmp_path / "alice.db")
    assert scheduler.run_scan_cycle("alice", now=clock())["status"] == "busy"
    runner.release.set()
    worker.join(2)
    assert not worker.is_alive() and outcomes == [{"status": "cancelled"}]
    assert store.load("alice") is None


def test_provider_failure_preserves_last_known_but_not_current_and_recovers(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    first = scheduler.current_state("alice")
    runner.fail = True
    clock.advance(120)
    assert scheduler.run_due_once(now=clock())["status"] == "failed"
    failed = scheduler.current_state("alice")
    assert failed["status"] == failed["freshness"]["state"] == "stale"
    assert failed["top_candidates"] == []
    assert failed["last_known_candidates"][0]["ticker"] == first["top_candidates"][0]["ticker"]
    assert failed["last_successful_scan"] == first["last_successful_scan"]
    assert "secret-provider-token" not in str(failed)
    runner.fail = False
    clock.advance(120)
    assert scheduler.run_due_once(now=clock())["status"] == "completed"
    recovered = scheduler.current_state("alice")
    assert recovered["status"] == "ready"
    assert recovered["last_successful_scan"] == clock().isoformat()
    assert recovered["diagnostics"]["last_failure"] is None


def test_state_write_failure_is_fail_closed_and_does_not_hammer_providers(tmp_path, monkeypatch):
    scheduler, runner, clock, store, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    original = store.save

    def fail_write(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(store, "save", fail_write)
    clock.advance(120)
    assert scheduler.run_due_once(now=clock())["status"] == "failed"
    assert scheduler.current_state("alice")["top_candidates"] == []
    assert scheduler.run_due_once(now=clock())["status"] == "idle"
    assert len(runner.calls) == 2
    monkeypatch.setattr(store, "save", original)
    clock.advance(120)
    assert scheduler.run_due_once(now=clock())["status"] == "completed"


def test_scanner_storage_failure_does_not_break_broker_activation(tmp_path, monkeypatch):
    scheduler, _, _, store, _ = build(tmp_path)

    def fail_read(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(store, "load", fail_read)
    scheduler.activate_user("bob", tmp_path / "bob.db")
    state = scheduler.current_state("bob")
    assert state["status"] == "unavailable"
    assert state["diagnostics"]["last_failure"]["reason"].startswith("state_read_failed")


def test_successful_empty_scan_clears_current_results_not_just_hiding_failure(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    runner.empty = True
    clock.advance(120)
    scheduler.run_scan_cycle("alice", "active", now=clock())
    state = scheduler.current_state("alice")
    assert state["status"] == "no_high_quality_candidates"
    assert state["top_candidates"] == state["last_known_candidates"] == []
    assert state["previous_snapshot"]["candidates"]


def test_partial_failure_preserves_new_valid_candidates_and_diagnostics(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    runner.partial = True
    scheduler.run_scan_cycle("alice", now=clock())
    state = scheduler.current_state("alice")
    assert state["status"] == "partial_failure" and len(state["top_candidates"]) == 1
    assert state["diagnostics"]["partial_failure"] is True
    assert state["diagnostics"]["provider_failure_count"] == 1
    assert state["top_candidates"][0]["eligible_for_current"] is False


def test_all_failed_page_is_not_advanced_or_treated_as_empty_success(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    runner.partial, runner.empty = True, True
    scheduler.run_scan_cycle("alice", now=clock())
    state = scheduler.current_state("alice")
    assert state["universe"]["next_offset"] == 0
    assert state["last_successful_scan"] is None
    assert state["diagnostics"]["last_cycle"]["partial_failure"] is True
    assert state["diagnostics"]["last_cycle"]["provider_failure_count"] == 1


def test_yahoo_delayed_results_are_not_highest_quality_current_signals(tmp_path):
    scheduler, _, clock, _, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    state = scheduler.current_state("alice")
    assert state["freshness"]["state"] == "delayed"
    row = state["top_candidates"][0]
    assert row["scanner_freshness"]["state"] == "delayed"
    assert row["eligible_for_current"] is False
    assert row["probability_up"] == .73 and row["opportunity_score"] == 90


@pytest.mark.parametrize("feature_age,expected,eligible", [(30, "current", True), (120, "current", True),
                                                           (121, "delayed", False), (1140, "delayed", False),
                                                           (1201, "stale", False)])
def test_feature_age_ideal_and_technical_ceiling_are_distinct(tmp_path, feature_age, expected, eligible):
    scheduler, runner, clock, _, _ = build(tmp_path)
    runner.provider = {"features": "synthetic_nondelayed_source", "feature_feed_delayed": False}
    runner.modifications = {"delayed": False, "feature_timestamp": (clock() - timedelta(seconds=feature_age)).isoformat()}
    scheduler.run_scan_cycle("alice", now=clock())
    state = scheduler.current_state("alice")
    row = (state["top_candidates"] or state["last_known_candidates"])[0]
    assert row["scanner_freshness"]["state"] == expected
    assert row["eligible_for_current"] is eligible
    if feature_age == 1140:
        assert row["scanner_freshness"]["penalty_points"] == pytest.approx(9.4444)
        assert row["freshness_adjusted_score"] < row["opportunity_score"] == 90


def test_known_delayed_provider_cannot_be_overridden_by_missing_candidate_flag(tmp_path):
    scheduler, runner, clock, _, _ = build(tmp_path)
    runner.modifications = {"delayed": None}
    scheduler.run_scan_cycle("alice", now=clock())
    row = scheduler.current_state("alice")["top_candidates"][0]
    assert row["scanner_freshness"]["state"] == "delayed"
    assert row["eligible_for_current"] is False


def test_state_ages_out_on_read_without_any_background_mutation(tmp_path):
    scheduler, _, clock, store, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    before = store.load("alice")
    clock.advance(121)
    stale = scheduler.current_state("alice")
    assert stale["freshness"]["state"] == "stale"
    assert stale["top_candidates"] == []
    assert stale["last_known_candidates"][0]["scanner_freshness"]["price_age_seconds"] == 121
    assert store.load("alice") == before


def test_metadata_and_original_stage_diagnostics_survive_state_projection(tmp_path):
    scheduler, _, clock, _, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    state = scheduler.current_state("alice")
    assert state["provider"]["features"] == "mock_yahoo"
    assert state["top_candidates"][0]["provider"] == "mock_alpaca"
    assert state["diagnostics"]["stage_counts"]["screened_count"] == 2
    assert state["diagnostics"]["exclusion_counts"] == {"liquidity": 0}
    assert "$1M" in state["diagnostics"]["volume_semantics"]


@pytest.mark.parametrize("restart_delay", [60, 600])
def test_restart_recovers_rotation_and_active_set_but_never_marks_saved_data_fresh(tmp_path, restart_delay):
    scheduler, runner, clock, store, _ = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    scheduler.stop()
    clock.advance(restart_delay)
    restarted = ScannerScheduler(ScannerStateStore(store.path), lambda *_: runner, lambda _: True,
                                 settings(), clock=clock)
    assert restarted.current_state("alice")["freshness"]["state"] == "stale"
    restarted.activate_user("alice", tmp_path / "alice.db")
    state = restarted.current_state("alice")
    assert state["top_candidates"] == [] and state["freshness"]["restored_unverified"] is True
    assert state["active_candidate_count"] == 2
    assert state["universe"]["next_offset"] == 2
    restarted.run_due_once(now=clock())
    assert runner.calls[-1] == ["CCC", "DDD"]
    assert restarted.current_state("alice")["freshness"]["restored_unverified"] is False


def test_user_state_isolation_and_disconnect_stop_network_work(tmp_path):
    scheduler, runner, clock, _, connected = build(tmp_path)
    scheduler.run_scan_cycle("alice", now=clock())
    assert scheduler.current_state("bob")["top_candidates"] == []
    assert scheduler.current_state("bob")["active_candidate_count"] == 0
    connected["alice"] = False
    clock.advance(600)
    assert scheduler.run_due_once(now=clock())["status"] == "idle"
    assert scheduler.current_state("alice")["top_candidates"] == []
    assert len(runner.calls) == 1


def test_settings_are_centralized_and_invalid_aggressive_intervals_are_rejected():
    defaults = ScannerSettings.from_env({})
    assert defaults.broad_interval_seconds == 600
    assert defaults.active_interval_seconds == 120
    assert defaults.page_size == 250
    assert ScannerSettings.from_env({"ORION_SCANNER_ENABLED": "false"}).enabled is False
    with pytest.raises(ValueError, match="Minimum scanner intervals"):
        ScannerSettings.from_env({"ORION_SCANNER_ACTIVE_INTERVAL_SECONDS": "5"})
