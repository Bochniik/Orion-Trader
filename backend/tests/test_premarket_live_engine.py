from datetime import datetime, timezone

from app.services.premarket_live_engine import (
    ORION_SCORE_SEMANTICS,
    premarket_session_active,
    synthesize_live_premarket_candidate,
)

UTC = timezone.utc
PREMARKET_NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)  # 08:00 ET


def signal(direction, probability_up, *, move=0.55, gate=True):
    confidence = max(probability_up, 1.0 - probability_up)
    return {
        "raw_direction": direction,
        "direction": direction if gate else "NO_TRADE",
        "probability_up": probability_up,
        "probability_down": 1.0 - probability_up,
        "direction_confidence": confidence,
        "normalized_predicted_move": move,
        "model_agreement": True,
        "research_gate_passed": gate,
        "predicted_return_pct": move if direction == "UP" else -move,
    }


def outlook(*signals):
    names = ("premarket_5m", "premarket_15m", "premarket_30m")
    return {
        "available": True,
        "research_only": True,
        "signals": {name: value for name, value in zip(names, signals)},
    }


def strong_setup():
    return {"score": 86.0, "data_quality_component": 94.0}


def strong_rank():
    return {
        "premarket_rank_score": 88.0,
        "premarket_rank_components": {"data_quality_score": 94.0},
    }


def test_session_gate_is_only_0400_to_0930_et_weekdays():
    assert premarket_session_active(datetime(2026, 10, 8, 8, 0, tzinfo=UTC)) is True  # 04:00 ET
    assert premarket_session_active(datetime(2026, 10, 8, 13, 29, tzinfo=UTC)) is True  # 09:29 ET
    assert premarket_session_active(datetime(2026, 10, 8, 13, 30, tzinfo=UTC)) is False
    assert premarket_session_active(datetime(2026, 10, 10, 12, 0, tzinfo=UTC)) is False


def test_bullish_v5_consensus_produces_separate_probability_and_orion_score():
    result = synthesize_live_premarket_candidate(
        ticker="NVDA",
        setup=strong_setup(),
        rank=strong_rank(),
        v5_outlook=outlook(
            signal("UP", 0.62, move=0.8),
            signal("UP", 0.60, move=0.7),
            signal("UP", 0.58, move=0.6),
        ),
        now=PREMARKET_NOW,
    )

    assert result["available"] is True
    assert result["direction"] == "UP"
    assert result["probability_up"] > result["probability_down"]
    assert result["research_gate_pass_count"] == 3
    assert result["horizon_consistency"] == 1.0
    assert 0 < result["premarket_orion_score"] <= 100
    assert result["premarket_orion_score"] != result["probability_up"] * 100
    assert result["score_semantics"] == ORION_SCORE_SEMANTICS
    assert result["actionable"] is False


def test_bearish_consensus_is_scored_symmetrically_not_penalized_for_direction():
    bullish = synthesize_live_premarket_candidate(
        ticker="A",
        setup=strong_setup(),
        rank=strong_rank(),
        v5_outlook=outlook(
            signal("UP", 0.62, move=0.8),
            signal("UP", 0.60, move=0.7),
            signal("UP", 0.58, move=0.6),
        ),
        now=PREMARKET_NOW,
    )
    bearish = synthesize_live_premarket_candidate(
        ticker="B",
        setup=strong_setup(),
        rank=strong_rank(),
        v5_outlook=outlook(
            signal("DOWN", 0.38, move=0.8),
            signal("DOWN", 0.40, move=0.7),
            signal("DOWN", 0.42, move=0.6),
        ),
        now=PREMARKET_NOW,
    )

    assert bearish["direction"] == "DOWN"
    assert bearish["probability_down"] > bearish["probability_up"]
    assert bearish["premarket_orion_score"] == bullish["premarket_orion_score"]


def test_no_gate_cannot_be_promoted_by_high_setup_or_rank_score():
    result = synthesize_live_premarket_candidate(
        ticker="SPY",
        setup={"score": 100.0, "data_quality_component": 100.0},
        rank={"premarket_rank_score": 100.0},
        v5_outlook=outlook(
            signal("UP", 0.53, move=0.1, gate=False),
            signal("UP", 0.52, move=0.1, gate=False),
            signal("UP", 0.51, move=0.1, gate=False),
        ),
        now=PREMARKET_NOW,
    )

    assert result["research_gate_pass_count"] == 0
    assert result["direction"] == "NO_TRADE"
    assert result["premarket_orion_score"] <= 54.0


def test_v5_unavailable_fails_closed_even_with_strong_setup():
    result = synthesize_live_premarket_candidate(
        ticker="META",
        setup=strong_setup(),
        rank=strong_rank(),
        v5_outlook={"available": False, "reason": "training_feed_mismatch_requires_sip"},
        now=PREMARKET_NOW,
    )

    assert result["available"] is False
    assert result["direction"] == "NO_TRADE"
    assert result["premarket_orion_score"] == 0.0
    assert result["reason"] == "training_feed_mismatch_requires_sip"


def test_outside_premarket_fails_closed():
    result = synthesize_live_premarket_candidate(
        ticker="MSFT",
        setup=strong_setup(),
        rank=strong_rank(),
        v5_outlook=outlook(
            signal("UP", 0.62), signal("UP", 0.61), signal("UP", 0.60)
        ),
        now=datetime(2026, 10, 8, 14, 0, tzinfo=UTC),  # 10:00 ET
    )

    assert result["available"] is False
    assert result["reason"] == "outside_premarket_session"
    assert result["direction"] == "NO_TRADE"
    assert result["premarket_orion_score"] == 0.0
