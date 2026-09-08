"""Regression for a real partial scan with valid market data but zero model picks.

Fixtures only exercise publication/rotation; no provider calls or fabricated
production observations are made.
"""
from copy import deepcopy

import pytest

from app.services.continuous_scanner import ScannerScheduler
from app.services.market_intelligence import compact_observation
from test_continuous_scanner import build
from test_staged_market_scanner import screening


def partial_without_picks(runner, clock, valid_count=1):
    original = runner.scan
    def scan(*args, **kwargs):
        result = original(*args, **kwargs)
        selected = runner.calls[-1]
        result.update(candidates=[], active_candidates=[], partial_failure=True,
                      errors=["provider batch incomplete"] * 3)
        result["stage_counts"].update(valid_data_count=valid_count, fully_analyzed=0, model_evaluations=0, returned=0)
        rows = [compact_observation(selected[0], screening(data_timestamp=clock().isoformat()), clock())] if valid_count == 1 else []
        result.update(market_intelligence_rows=rows, market_observed_symbols=[r["ticker"] for r in rows])
        return result
    runner.scan = scan


def test_partial_market_page_publishes_without_model_picks_and_next_page_runs(tmp_path):
    scheduler, runner, clock, store, _ = build(tmp_path)
    partial_without_picks(runner, clock)
    assert scheduler.run_due_once(now=clock())["status"] == "completed"
    state = scheduler.current_state("alice")
    assert state["status"] == "partial_failure"
    assert state["generated_at"] == state["last_successful_scan"] == clock().isoformat()
    assert state["universe"]["total_symbols"] == 5
    assert state["universe"]["current_page"] == 1
    assert state["universe"]["next_offset"] == 2
    assert state["top_candidates"] == [] and state["active_candidate_count"] == 0
    assert state["diagnostics"]["provider_failure_count"] == 3
    assert state["diagnostics"]["partial_failure"] is True
    assert state["diagnostics"]["stage_counts"]["valid_data_count"] == 1
    assert "No model-qualified Orion Picks" in state["message"]
    market = scheduler.market_intelligence("alice")
    assert market["categories"]["most_active"]["items"][0]["ticker"] == "AAA"
    assert store.load("alice")["snapshot"]["partial_failure"] is True
    clock.advance(600)
    scheduler.run_due_once(now=clock())
    assert runner.calls == [["AAA", "BBB"], ["CCC", "DDD"]]
    assert scheduler.current_state("alice")["universe"]["next_offset"] == 4


@pytest.mark.parametrize("count", [0, None, float("nan")])
def test_no_usable_market_data_still_fails_closed_without_advancing(count, tmp_path):
    scheduler, runner, clock, store, _ = build(tmp_path)
    partial_without_picks(runner, clock, count)
    assert scheduler.run_due_once(now=clock())["status"] == "failed"
    state = scheduler.current_state("alice")
    assert state["generated_at"] is None
    assert state["last_successful_scan"] is None
    assert state["universe"]["next_offset"] == 0
    assert (store.load("alice") or {}).get("snapshot") is None


def test_repeated_partial_pages_keep_previous_picks_stale_without_refreshing_them(tmp_path):
    scheduler, runner, clock, store, _ = build(tmp_path)
    scheduler.run_due_once(now=clock())
    previous = deepcopy(store.load("alice")["snapshot"])
    partial_without_picks(runner, clock)
    for _ in range(2):
        clock.advance(600)
        scheduler.run_due_once(now=clock())
        state = scheduler.current_state("alice")
        assert state["status"] == "partial_failure" and not state["top_candidates"]
        assert state["last_known_candidates"][0]["scanner_freshness"]["state"] == "stale"
        assert state["last_known_candidates"][0]["data_timestamp"] == previous["candidates"][0]["data_timestamp"]
        assert store.load("alice")["previous_snapshot"] == previous


def test_restart_preserves_partial_snapshot_and_completed_page_metadata(tmp_path):
    scheduler, runner, clock, store, _ = build(tmp_path)
    partial_without_picks(runner, clock)
    scheduler.run_due_once(now=clock())
    restarted = ScannerScheduler(store, lambda *_: runner, lambda _: True, scheduler.settings, clock=clock)
    state = restarted.current_state("alice")
    assert state["status"] == "stale"
    assert state["generated_at"] is not None
    assert state["universe"]["next_offset"] == 2
    assert state["diagnostics"]["partial_failure"] is True
    assert state["diagnostics"]["stage_counts"]["model_evaluations"] == 0
