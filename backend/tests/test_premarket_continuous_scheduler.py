from datetime import datetime, timezone

from app.services import premarket_continuous_scheduler as module
from app.services.premarket_continuous_scheduler import (
    PremarketContinuousScheduler,
    baseline_from_snapshot,
)


class FakeBroker:
    def __init__(self, connected=True):
        self.connected = connected

    def status(self, user_id):
        return {"connected": self.connected}

    def liquidity_candidates(self, user_id, limit=100):
        return ["AAA", "BBB"], []

    def snapshots(self, user_id, symbols):
        return {
            "AAA": {"prevDailyBar": {"c": 100.0, "v": 2_000_000}},
            "BBB": {"prevDailyBar": {"c": 50.0, "v": 500_000}},
        }


class FakeMarket:
    pass


def test_baseline_uses_completed_session_close_and_volume():
    result = baseline_from_snapshot({"prevDailyBar": {"c": 20, "v": 1_500_000}})
    assert result["previous_close"] == 20
    assert result["dollar_volume"] == 30_000_000


def test_cycle_waits_outside_premarket_without_provider_calls():
    now = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)
    scheduler = PremarketContinuousScheduler(FakeBroker(), FakeMarket(), interval_seconds=60)
    result = scheduler.run_cycle("u1", now=now)
    assert result == {"status": "waiting_for_premarket", "candidate_count": 0}


def test_cycle_fails_closed_when_provider_not_connected():
    # 08:00 ET on 2026-10-08.
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    scheduler = PremarketContinuousScheduler(FakeBroker(connected=False), FakeMarket(), interval_seconds=60)
    result = scheduler.run_cycle("u1", now=now)
    assert result["status"] == "provider_unavailable"
    assert scheduler.current_state("u1")["failure"]["reason"] == "alpaca_not_connected"


def test_live_cycle_builds_ranked_v5_board(monkeypatch):
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    scheduler = PremarketContinuousScheduler(FakeBroker(), FakeMarket(), interval_seconds=60, clock=lambda: now)
    scheduler.activate_user("u1")

    monkeypatch.setattr(module, "screen_premarket_candidates", lambda *args, **kwargs: {
        "status": "candidates_available",
        "items": [
            {
                "ticker": "AAA",
                "previous_close": 100.0,
                "baseline_dollar_volume": 200_000_000,
                "premarket_screen_score": 88.0,
            }
        ],
        "pool_count": 2,
        "fresh_observation_count": 1,
        "finalist_count": 1,
    })

    setup = {
        "ticker": "AAA",
        "premarket_price": 103.0,
        "previous_close": 100.0,
        "gap_pct": 3.0,
        "data_timestamp": now.isoformat(),
        "predictive_as_of": now.isoformat(),
        "predictive_feed": "sip",
        "feed": "iex",
        "delayed": False,
        "premarket_score": 80.0,
        "analysis_status": "full_premarket_analysis",
        "analysis": {"score": 80.0, "data_quality_component": 100.0},
        "predictive_outlook": {
            "premarket_research": {
                "available": True,
                "signals": {
                    "premarket_5m": {
                        "probability_up": 0.62,
                        "probability_down": 0.38,
                        "direction_confidence": 0.62,
                        "normalized_predicted_move": 0.5,
                        "raw_direction": "UP",
                        "model_agreement": True,
                        "research_gate_passed": True,
                    },
                    "premarket_15m": {
                        "probability_up": 0.60,
                        "probability_down": 0.40,
                        "direction_confidence": 0.60,
                        "normalized_predicted_move": 0.4,
                        "raw_direction": "UP",
                        "model_agreement": True,
                        "research_gate_passed": True,
                    },
                    "premarket_30m": {
                        "probability_up": 0.58,
                        "probability_down": 0.42,
                        "direction_confidence": 0.58,
                        "normalized_predicted_move": 0.3,
                        "raw_direction": "UP",
                        "model_agreement": True,
                        "research_gate_passed": True,
                    },
                },
            }
        },
    }
    monkeypatch.setattr(scheduler.adapter, "build", lambda *args, **kwargs: setup)
    monkeypatch.setattr(module, "rank_premarket_candidate", lambda item: {
        **item,
        "premarket_rank_score": 82.0,
        "premarket_rank_components": {"data_quality_score": 100.0},
    })

    result = scheduler.run_cycle("u1", now=now)
    state = scheduler.current_state("u1")

    assert result == {"status": "ready", "candidate_count": 1}
    assert state["candidates"][0]["ticker"] == "AAA"
    assert state["candidates"][0]["direction"] == "UP"
    assert state["candidates"][0]["probability_up"] > 0.5
    assert state["candidates"][0]["premarket_orion_score"] > 0
    assert state["candidates"][0]["order_submission_enabled"] is False
    assert state["diagnostics"]["architecture"] == "continuous_live_premarket"
    assert state["diagnostics"]["frozen_checkpoints_are_evidence_only"] is True
